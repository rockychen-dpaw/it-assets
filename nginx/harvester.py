import yaml
import re
import os
import logging
import json
from datetime import date,datetime

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils import timezone

from data_storage import ResourceConsumeClient,AzureBlobStorage,LockSession
from .models import (Domain,SystemAlias,SystemEnv,WebApp,WebAppLocation,WebAppListen,WebServer,WebAppLocationServer)

from rancher.models import Cluster

logger = logging.getLogger(__name__)

class JSONEncoder(json.JSONEncoder):
    """
    A JSON encoder to support encode datetime
    """
    def default(self,obj):
        from data_storage.settings import TZ
        if isinstance(obj,datetime):
            return obj.astimezone(tz=TZ).strftime("%Y-%m-%d %H:%M:%S.%f")
        elif isinstance(obj,date):
            return obj.strftime("%Y-%m-%d")
        elif isinstance(obj,models.Model):
            return str(obj)

        return json.JSONEncoder.default(self,obj)

_resource_consume_client = None
def get_resource_consume_client():
    """
    Return the blob resource client
    """
    global _resource_consume_client
    if _resource_consume_client is None:
        _resource_consume_client = ResourceConsumeClient(
            AzureBlobStorage(settings.NGINX_STORAGE_CONNECTION_STRING,settings.NGINX_CONTAINER),
            settings.NGINX_RESOURCE_NAME,
            settings.RESOURCE_CLIENTID
        )
    return _resource_consume_client

upstream_block_re = re.compile("(\s+|^)upstream\s+(?P<name>[a-zA-Z0-9_\-]+)\s*{(?P<body>[^\}]+)}")
comments_re = re.compile("#[^\n]+(\n|$)")
upstream_server_re = re.compile("(^|\s+|;)\s*server\s+(?P<server>[a-zA-Z0-9_\-\.]+):(?P<port>[0-9]+)")
clientip_subnet_block_re = re.compile("(\s+|^)geo\s+\$(?P<name>[a-zA-Z0-9_\-]+)\s*{(?P<body>[^\}]+)}")
clientip_subnet_rule_re =  re.compile("^\s*if\s+\(\s*\$(?P<name>[a-zA-Z0-9_\-]+)\s*=\s*0\s*\)\s*{\s*return\s*(403|401)\s*;?\s*}\s*;?\s*$",re.IGNORECASE)

sso_auth_domains = [
    (WebAppLocation.SSO_AUTH_TO_DBCA,WebApp.SSO_AUTH_TO_DBCA),
    (WebAppLocation.SSO_AUTH_TO_DPAW,WebApp.SSO_AUTH_TO_DPAW),
    (WebAppLocation.SSO_AUTH_TO_UAT,WebApp.SSO_AUTH_TO_UAT)
]

def process_nginx(nginx_config_resources):
    jsons = {}
    for status,metadata,filename in nginx_config_resources:
        with open(filename,'r') as f:
            jsons[metadata["resource_id"]] = yaml.load(f.read())

    nginx_json = jsons["nginx.yml"]
    nginx_config_json = jsons["nginx-config.yml"]
    nginx_includes = nginx_config_json["nginx_includes"]

    #parse pre.conf
    clientip_subnets = {}
    upstream_servers = {}
    pre_conf = nginx_includes.get("pre.conf")
    if pre_conf:
        #remove comments
        pre_conf = comments_re.sub("\n",pre_conf)
        #parse upstream
        for m in upstream_block_re.finditer(pre_conf):
            name = m.group("name")
            body = m.group("body")
            upstream_servers[name] = []
            for s_m in upstream_server_re.finditer(body):
                upstream_servers[name].append([s_m.group("server"),int(s_m.group("port"))])
        logger.debug("""upstream servers:
{}
""".format(json.dumps(upstream_servers,cls=JSONEncoder,indent="    ")))

        #parse clientip_subnets
        for m in clientip_subnet_block_re.finditer(pre_conf):
            name = m.group("name")
            clientip_subnets[name] = m.group(0).strip()

        logger.debug("""clientip_subnets:
{}
""".format(json.dumps(clientip_subnets,cls=JSONEncoder,indent="    ")))

    includes = {}
    def expand_include(include,prefix=""):
        key = (include,prefix)
        if key in includes:
            return includes[key]
        if include not in nginx_includes:
            includes[key] = "{}include {};".format(prefix,include)
            return includes[key]

        include_config = nginx_includes[include]
        if not isinstance(include_config,str):
            raise Exception("The nginx include({}) is type({}),Not supported".foramt(include,include_config.__class__.__name__))
        include_config_lines = include_config.split(os.linesep)

        i = len(include_config_lines) - 1
        while i >= 0:
            line = include_config_lines[i]
            striped_line = line.strip()
            if "include " in striped_line:
                #only try to split the line with multi statements into multi lines  if "include" statement is included in the line
                subprefix = line[0:line.index(striped_line)]
                sublines = [l.strip() for l in striped_line.split(";") if l.strip()]
                if len(sublines) > 1:
                    del include_config_lines[i]
                    sublines.reverse()
                    for l in sublines:
                        include_config_lines.insert(i,"{}{};".format(subprefix,l))
            i -= 1

        #expand the nested include 
        i = len(include_config_lines) - 1
        while i >= 0:
            line = include_config_lines[i]
            striped_line = line.strip()
            subprefix = line[0:line.index(striped_line)]
            if striped_line.startswith("include"):
                #nested  include
                nested_include = striped_line.split(" ")[1]
                #remove the ending ';'
                if nested_include[-1] == ";":
                    nested_include = nested_include[:-1].strip()
                expanded_include = expand_include(nested_include,prefix="{}{}".format(prefix,subprefix))
                include_config_lines[i]=expanded_include
            else:
                include_config_lines[i]="{}{}".format(prefix,line)

            i -= 1

        #join all lines into a configuration string
        """
        if prefix:
            i = len(include_config_lines) - 1
            while i >= 0:
                line = include_config_lines[i]
                include_config_lines[i]="{}{}".format(prefix,line)
                i -= 1
        """
        includes[key] = os.linesep.join(include_config_lines)
        return includes[key]


    nginx_servers = nginx_json["nginx_servers"]
    expanded_server_config = ""
    servers  = {}
    clientip_subnet = None
    #combine the nginx config 
    for server,server_config in nginx_servers.items():
        clientip_subnet = None
        expanded_server_config = ""
        if "redirect" in server_config:
            server_redirect = server_config["redirect"]
            expanded_server_config = """{}
redirect {};""".format(expanded_server_config,server_redirect)
        if "includes" in server_config:
            #expand includes
            server_includes = server_config["includes"]
            for include in server_includes:
                expanded_include = expand_include(include)
                #check whether the include is a clientip subnet rule
                m = clientip_subnet_rule_re.search(expanded_include)
                if m:
                    #clientip subnet rule
                    clientip_subnet = m.group('name')
                    if clientip_subnet not in clientip_subnets:
                        raise Exception("Geo block for ({}) Not Found".format(clientip_subnet))
                    expanded_include = """{}
{}""".format(expanded_include,clientip_subnets[clientip_subnet])
                    
                expanded_server_config = """{}
{}""".format(expanded_server_config,expanded_include)
        if "locations" in server_config:
            server_locations = server_config["locations"]
            for location in server_locations:
                location_path = location["path"]
                location_rules = location["rules"]
                i = len(location_rules) - 1
                while i >= 0:
                    rule = location_rules[i]
                    if rule.startswith("include"):
                        #nested  include
                        rule_include = rule.split(" ")[1]
                        #remove the ending ';'
                        if rule_include[-1] == ";":
                            rule_include = rule_include[:-1].strip()
                        expanded_include = expand_include(rule_include,"    ")
                        location_rules[i]=expanded_include
                    else:
                        location_rules[i]="    {}".format(location_rules[i])
                    i -= 1

                expanded_server_config = """{}
location {} {{
{}
}}""".format(expanded_server_config,location_path,os.linesep.join(location_rules))

        expanded_server_config = expanded_server_config.strip()
        servers[server] = (expanded_server_config,clientip_subnet)
        #print("{}\n{}\n\n".format(server,expanded_server_config))

    #parse the combined nginx configure
    domains = Domain.objects.all().order_by("-score")
    system_envs = list(SystemEnv.objects.all())
    system_envs.sort(key=lambda e:len(e.name),reverse=True)
    redirect_servers = []
    serverids = []
    redirect_serverids = []
    for server in sorted(servers.keys(),key=lambda name:name.split(".",1)[0]):
        server_config,clientip_subnet = servers[server]
        try:
            server_alias,server_domain,server_env = parse_server(server,domains=domains,system_envs = system_envs)
            #print("============" + server + "\t"  + server_alias.name + "\t" + server_env.name)
            redirect_to_server,redirect_path,server_listens,server_locations = parse_server_config(server,server_config,upstream_servers)
        except Exception as ex:
            logger.error(str(ex))
            raise ex

        if redirect_to_server:
            logger.debug("""name={}
domain={}
env={}

redirect to {}{}""".format(server_alias,server_domain,server_env,redirect_to_server,redirect_path or ""))
            redirect_servers.append((server,server_config,server_alias,server_domain,server_env,redirect_to_server,redirect_path,clientip_subnet))
            continue
        else:
            logger.debug("""name={}
domain={}
env={}

Listens
{}

Locations
{}""".format(server_alias,server_domain,server_env,os.linesep.join("host={listen_host} port={listen_port} https={https}".format(**l) for l in server_listens),json.dumps(server_locations,cls=JSONEncoder,indent="    ")))
        #save app
        app = WebApp.objects.filter(name=server).first()
        if not app:
            app = WebApp(name = server,config_modified=timezone.now())

        sso_required = False
        for location in server_locations:
            if location["auth_type"] in (WebAppLocation.SSO_AUTH,WebAppLocation.SSO_AUTH_DUAL):
                sso_required = True
                break

        auth_domain = WebApp.SSO_AUTH_NOT_REQUIRED
        if sso_required:
            for location in server_locations:
                a_domain = next((t for t in sso_auth_domains if t[0] == location["auth_type"]),None)
                if a_domain:
                    auth_domain = a_domain[1]
                    break

        update_fields = []
        for f,val in [
            ("system_alias",server_alias),
            ("system_env",server_env),
            ("domain",server_domain),
            ("configure_txt",server_config),
            ("redirect_to",None),
            ("redirect_to_other",None),
            ("redirect_path",None),
            ("clientip_subnet",clientip_subnet),
            ("auth_domain",auth_domain)
        ]:
            app.set_config(f,val,update_fields)

        if not app.pk:
            app.save()
            serverids.append(app.pk)
            logger.debug("Create the WebApp({})".format(app))
        else:
            serverids.append(app.pk)
            if update_fields:
                app.config_changed_columns = list(update_fields)
                update_fields.append("config_changed_columns")

                app.config_modified = timezone.now()
                update_fields.append("config_modified")

                update_fields.append("modified")

                app.save(update_fields=update_fields)
                logger.debug("Update the WebApp({}),update_fields={}".format(app,update_fields))

        #save app listen
        #delete the non-exist listens and update the changed listens
        for listen in list(WebAppListen.objects.filter(app = app)):
            index = len(server_listens) - 1
            server_listen = None
            while index >= 0:
                if server_listens[index]["listen_host"] == listen.listen_host and server_listens[index]["listen_port"] == listen.listen_port:
                    server_listen = server_listens[index]
                    del server_listens[index]
                    break
                index -= 1
            if server_listen:
                #found in the current configuration
                update_fields = []
                for f,val in [("https",server_listen["https"]),("configure_txt",server_listen["configure_txt"])]:
                    if getattr(listen,f) != val:
                        setattr(listen,f,val)
                        update_fields.append(f)
                if update_fields:
                    listen.config_changed_columns = list(update_fields)
                    update_fields.append("config_changed_columns")

                    listen.config_modified = timezone.now()
                    update_fields.append("config_modified")

                    update_fields.append("modified")

                    listen.save(update_fields=update_fields)
                    logger.debug("Update the WebAppListen({1}) from server({0}),update_fields={2}".format(app,listen,update_fields))
            else:
                #not found in the current configuration,delete it
                listen.delete()
                logger.debug("Delete the WebAppListen({1}) from server({0})".format(app,listen))

        #create the new listen
        for server_listen in server_listens:
            listen = WebAppListen(
                app = app,
                listen_host = server_listen["listen_host"],
                listen_port = server_listen["listen_port"],
                https = server_listen["https"],
                configure_txt = server_listen["configure_txt"],
                config_modified = timezone.now()
            )
            listen.save()
            logger.debug("Create the WebAppListen({1}) from server({0})".format(app,listen))

        #save app location
        for location in list(WebAppLocation.objects.filter(app = app)):
            index = len(server_locations) - 1
            server_location = None
            while index >= 0:
                if server_locations[index]["location_type"] == location.location_type and server_locations[index]["location"] == location.location:
                    server_location = server_locations[index]
                    del server_locations[index]
                    break
                index -= 1
            if server_location:
                #found in the current configuration
                update_fields = []
                for f,val in [
                    ("cors_enabled",server_location["cors_enabled"]),
                    ("auth_type",server_location["auth_type"]),
                    ("redirect",server_location["redirect"]),
                    ("return_code",server_location["return_code"]),
                    ("refuse",server_location["refuse"]),
                    ("forward_protocol",server_location["forward_protocol"]),
                    ("forward_path",server_location["forward_path"]),
                    ("configure_txt",server_location["configure_txt"])
                ]:
                    location.set_config(f,val,update_fields)
                if update_fields:
                    location.config_changed_columns = list(update_fields)
                    update_fields.append("config_changed_columns")

                    location.config_modified = timezone.now()
                    update_fields.append("config_modified")

                    update_fields.append("modified")

                    location.save(update_fields=update_fields)
                    logger.debug("Update the WebAppLocation({1}) from server({0}),update_fields={2}".format(app,location,update_fields))

                if server_location["forward_servers"]:
                    save_location_forward_servers(location,server_location["forward_servers"],created=False)
            else:
                #not found in the current configuration,delete it
                location.delete()
                logger.debug("Delete the WebAppLocation({1}) from server({0})".format(app,location))

        #create the new app location
        for server_location in server_locations:
            location = WebAppLocation(
                app = app,
                location_type = server_location["location_type"],
                location = server_location["location"],
                config_modified = timezone.now()
            )
            update_fields = []
            for f,val in [
                ("cors_enabled",server_location["cors_enabled"]),
                ("auth_type",server_location["auth_type"]),
                ("redirect",server_location["redirect"]),
                ("return_code",server_location["return_code"]),
                ("refuse",server_location["refuse"]),
                ("forward_protocol",server_location["forward_protocol"]),
                ("forward_path",server_location["forward_path"]),
                ("configure_txt",server_location["configure_txt"])
            ]:
                location.set_config(f,val,update_fields)
            location.save()
            logger.debug("Create the WebAppLocation({1}) from server({0})".format(app,location))
            if server_location["forward_servers"]:
                save_location_forward_servers(location,server_location["forward_servers"],created=True)


    #process webapp which redirect to another dbca webapp
    created_servers = 0
    while redirect_servers:
        index = len(redirect_servers) - 1
        created_servers = 0
        while index >= 0:
            server,server_config,server_alias,server_domain,server_env,redirect_server,redirect_path,clientip_subnet = redirect_servers[index]
            try:
                #save app
                app = WebApp.objects.filter(name=server).first()
                if not app:
                    app = WebApp(name = server,config_modified=timezone.now())

                try:
                    target_server = WebApp.objects.get(name=redirect_server)
                except ObjectDoesNotExist as ex:
                    target_server = None
                    continue

                update_fields = []
                for f,val in [
                    ("system_alias",server_alias),
                    ("system_env",server_env),
                    ("domain",server_domain),
                    ("redirect_to",target_server),
                    ("redirect_to_other",None),
                    ("redirect_path",redirect_path),
                    ("clientip_subnet",clientip_subnet),
                    ("auth_domain",target_server.auth_domain),
                    ("configure_txt",server_config)
                ]:
                    app.set_config(f,val,update_fields)

                if not app.pk:
                    app.save()
                    redirect_serverids.append(app.pk)
                    logger.debug("Create the WebApp({})".format(app))
                    created_servers += 1
                else:
                    redirect_serverids.append(app.pk)
                    if update_fields:
                        app.config_changed_columns = list(update_fields)
                        update_fields.append("config_changed_columns")

                        app.config_modified = timezone.now()
                        update_fields.append("config_modified")

                        update_fields.append("modified")

                        app.save(update_fields=update_fields)
                        logger.debug("Update the WebApp({}),update_fields={}".format(app,update_fields))
        
                    #delete app listen data
                    WebAppListen.objects.filter(app = app).delete()
        
                    #delete app location data
                    WebAppLocation.objects.filter(app = app).delete()

                del redirect_servers[index]
            finally:
                index -= 1

        if created_servers == 0:
            break

    #process webapp which redirect to external webapp
    if redirect_servers:
        for server,server_config,server_alias,server_domain,server_env,redirect_server,redirect_path,clientip_subnet in redirect_servers:
            #save app
            app = WebApp.objects.filter(name=server).first()
            if not app:
                app = WebApp(name = server,config_modified=timezone.now())

            update_fields = []
            for f,val in [
                ("system_alias",server_alias),
                ("system_env",server_env),
                ("domain",server_domain),
                ("redirect_to",None),
                ("redirect_to_other",redirect_server),
                ("redirect_path",redirect_path),
                ("clientip_subnet",clientip_subnet),
                ("auth_domain",WebApp.SSO_AUTH_NOT_REQUIRED),
                ("configure_txt",server_config)
            ]:
                app.set_config(f,val,update_fields)

            if not app.pk:
                app.save()
                redirect_serverids.append(app.pk)
                logger.debug("Create the WebApp({})".format(app))
            else:
                redirect_serverids.append(app.pk)
                if update_fields:
                    app.config_changed_columns = list(update_fields)
                    update_fields.append("config_changed_columns")

                    app.config_modified = timezone.now()
                    update_fields.append("config_modified")

                    update_fields.append("modified")

                    app.save(update_fields=update_fields)
                    logger.debug("Update the WebApp({}),update_fields={}".format(app,update_fields))
    
                #delete app listen data
                WebAppListen.objects.filter(app = app).delete()
    
                #delete app location data
                WebAppLocation.objects.filter(app = app).delete()

                
    #delete the not-exist server which redirect to other webapp
    del_objs = WebApp.objects.exclude(pk__in=redirect_serverids).filter(models.Q(redirect_to__isnull=False) | models.Q(redirect_to_other__isnull=False)).delete()
    if del_objs[0]:
        logger.debug("Delete {} WebApp which redirect to other application,deleted objects = {}".format(del_objs[0],del_objs[1]))

    #delete the not-exist server which doesn't redirect to other webapp
    del_objs = WebApp.objects.exclude(pk__in=serverids).filter(redirect_to__isnull=True,redirect_to_other__isnull=True).delete()
    if del_objs[0]:
        logger.debug("Delete {} WebApp which doesn't redirect to other application,deleted objects = {}".format(del_objs[0],del_objs[1]))

    logger.info("Parsing nginx configuration successfully.")


def save_location_forward_servers(app_location,location_servers,created=False):
    if WebAppLocationServer.objects.filter(location = app_location,user_added=True).exists():
        #user added some forward servers
        if not WebAppLocationServer.objects.filter(location = app_location,user_added=False).exists():
            #user deleted all forward servers, no need to populate the forward servers from confguration file
            return

    #Get WebServer object with name, create it if it doesn't exist
    for location_server in location_servers:
        if isinstance(location_server[0],WebServer):
            continue

        hostcategory = None
        hostname = WebServer.get_hostname(location_server[0])
        other_name = None if hostname == location_server[0] else location_server[0]
        if Cluster.objects.filter(models.Q(name=hostname) | models.Q(ip=hostname)).first():
            hostcategory = WebServer.RANCHER_CLUSTER
        try:
            location_server[0] = WebServer.objects.get(name=hostname)
            update_fields = []
            if hostcategory and location_server[0].category != hostcategory:
                location_server[0].category = hostcategory
                update_fields.append("category")

            if other_name and (not location_server[0].other_names or other_name not in location_server[0].other_names):
                if location_server[0].other_names:
                    location_server[0].other_names.append(other_name)
                else:
                    location_server[0].other_names = [other_name]
                update_fields.append("other_names")
            if update_fields:
                location_server[0].save(update_fields=update_fields)
        except ObjectDoesNotExist as ex:
            location_server[0] = WebServer(name=hostname,category=hostcategory,other_names=[other_name] if other_name else None)
            location_server[0].save()


    #save location forward servers

    #delete the removed webapplicationserver
    founded_index = set()
    for server in list(WebAppLocationServer.objects.filter(location = app_location)):
        index = len(location_servers) - 1
        location_server = None
        while index >= 0:
            if location_servers[index][0] == server.server and location_servers[index][1] == server.port:
                location_server = location_servers[index]
                founded_index.add(index)
                break
            index -= 1
        if not location_server and not server.user_added:
            #not found in the current configuration,delete it
            server.delete()
            logger.debug("Delete the WebAppLocationServer({1}) from location({0})".format(server,app_location))

    #create location forward server
    index = len(location_servers) - 1
    while index >= 0:
        location_server = location_servers[index]
        if index in founded_index:
            #already created
            server = WebAppLocationServer.objects.get(location = app_location,server=location_server[0],port=location_server[1])
            rancher_workload = server.locate_rancher_workload()
            if rancher_workload != server.rancher_workload:
                server.rancher_workload = rancher_workload
                server.save(update_fields=["rancher_workload"])
                logger.debug("Update the WebAppLocationServer({1}) from location({0})".format(app_location,server))
        else:
            #new location server, create it
            server = WebAppLocationServer(
                location = app_location,
                server = location_server[0],
                port = location_server[1],
                user_added = False
            )
            server.rancher_workload = server.locate_rancher_workload()
            server.save()
            logger.debug("Create the WebAppLocationServer({1}) from location({0})".format(app_location,server))
        index -= 1


def parse_server(server,domains = None,system_envs = None):
    domains = domains or Domain.objects.all().order_by("-score")
    if not system_envs:
        system_envs = list(SystemEnv.objects.all())
        system_envs.sort(key=lambda e:len(e.name))
    name = None
    domain = None
    system_env = None
    if server.startswith("www."):
        server = server[4:]
    for d in domains:
        if server.endswith(d.name):
            domain = d
            name = server[:(len(d.name) + 1) * -1]
            break

    if domain:
        if not name:
            name,domain_name = domain.name.split(".",1)
            domain = Domain.objects.get(name=domain_name)
    else:
        name = server
        domain=None

    for e in system_envs:
        if name.endswith(e.name):
            system_env = e
            name = name[:len(e.name) * -1]
            if name[-1] in ("-","_"):
                name = name[:-1]
            break

    if not system_env:
        separator = None
        if "-" in name :
            separator = "-"
        elif "_" in name:
            separator ="_"
        
        if separator:
            tmp_name = name
            while tmp_name :
                if SystemAlias.objects.filter(name=tmp_name).exists():
                    if tmp_name == name:
                        #no env suffix, prod environment
                        system_env = SystemEnv.objects.get(name="prod")
                    else:
                        #have env suffix, treat it as dev environment
                        system_env = SystemEnv.objects.get(name="dev")
                    name = tmp_name
                    break
                elif separator in tmp_name:
                    tmp_name = tmp_name.rsplit(separator,1)[0]
                else:
                    tmp_name = None



    name,created = SystemAlias.objects.get_or_create(name=name)
    if created:
        logger.info("Create the system alias({1}) for the server({0}) ".format(server,name))


    if not system_env:
        system_env = SystemEnv.objects.get(name="prod")

    return (name,domain,system_env)

listen_re = re.compile("^listen\s+(?P<host>[0-9a-zA-Z\-\_\.\*]+):(?P<port>[0-9]+)(\s+(?P<https>ssl))?(\s+|;|$)")

sso_auth_types = [
    (WebAppLocation.SSO_AUTH,re.compile("\s+auth_request\s+/sso/auth(\s+|;|\}|$)")),
    (WebAppLocation.SSO_AUTH_DUAL,re.compile("\s+auth_request\s+/sso/auth_dual(\s+|;|\}|$)")),
    (WebAppLocation.SSO_AUTH_TO_DBCA,re.compile("\s+(uwsgi_pass\s+|proxy_pass\s+https?:\/\/)authome_dbca(\s+|;|\}|$)")),
    (WebAppLocation.SSO_AUTH_TO_DPAW,re.compile("\s+(uwsgi_pass\s+|proxy_pass\s+https?:\/\/)authome_dpaw(\s+|;|\}|$)")),
    (WebAppLocation.SSO_AUTH_TO_UAT,re.compile("\s+(uwsgi_pass\s+|proxy_pass\s+https?:\/\/)authome_uat(\s+|;|\}|$)")),
    (WebAppLocation.NO_SSO_AUTH,None)
]
location_re = re.compile("(^|\s+)location\s+((?P<modifier>[\=\~\*\^]+)\s+)?(?P<location>[\S]+)\s*\{")
location_types = [
    (WebAppLocation.EXACT_LOCATION,"="),
    (WebAppLocation.CASE_SENSITIVE_REGEX_LOCATION,"~"),
    (WebAppLocation.CASE_INSENSITIVE_REGEX_LOCATION,"~*"),
    (WebAppLocation.NON_REGEX_LOCATION,"^~"),
    (WebAppLocation.PREFIX_LOCATION,None)
]

cors_re = re.compile("\s+add_header\s+(\'|\")Access-Control-Allow-Origin(\'|\")\s+(\'|\")\$http_origin(\'|\")\s+always\s*;")
redirect_re = re.compile("(^|\s+)redirect\s+(?P<target_server>[a-zA-Z0-9_\-\.]+)(?P<path>/[\S]*)?\s*;")

location_redirect_res = [
    re.compile("(^|\s+)return\s+(?P<http_code>[0-9]+)\s+(?P<location>[\S]+)(\s+|;|\}|$)"),
    re.compile("(^|\s+)rewrite\s+(?P<src>[\S]+)\s+(?P<target>[\S]+)\s+(redirect|permanent)")
]

location_refuse_res = [
    re.compile("(^|\s+)deny\s+all(\s+|;|\}|$)"),
]


protocol_types = [
    (WebAppLocation.HTTP,re.compile("(^|\s+)proxy_pass\s+http:\/\/(?P<server>[\$a-zA-Z0-9\_\-\.]+)(:(?P<port>[0-9]+))?(?P<path>/[\S]*)?(\s+|;|\}|$)")),
    (WebAppLocation.UWSGI,re.compile("(^|\s+)uwsgi_pass\s+(?P<server>[\$a-zA-Z0-9\_\-\.]+)(:(?P<port>[0-9]+))?(?P<path>/[\S]*)?(\s+|;|\}|$)")),
    (WebAppLocation.HTTPS,re.compile("(^|\s+)proxy_pass\s+https:\/\/(?P<server>[\$a-zA-Z0-9\_\-\.]+)(:(?P<port>[0-9]+))?(?P<path>/[\S]*)?(\s+|;|\?|$)"))
]

return_re = re.compile("(^|\s+)return\s+(?P<code>[0-9]+)(\s+|;|\}|$)")

internal_location_re = re.compile("(^|\s+)internal(\s+|;|\}|$)")
def parse_server_config(server,server_config,upstream_servers):
    config_lines = server_config.split(os.linesep)
    listens = []
    variables = []
    location_lines = None
    redirect_to_server = None
    redirect_path = None
    locations = []
    def _save_location(location_lines):
        if location_lines:
            configure_txt = os.linesep.join(location_lines)
            #replace the variables in locations
            for name,val in variables:
                configure_txt = configure_txt.replace(name,val)

            #location and location type
            location = None
            location_type = None
            m = location_re.search(configure_txt)
            if not m:
                raise Exception("""Can't find the location from location configuration""
{}""".format(configure_txt))
            location = m.group("location")
            location_type = next((o[0] for o in location_types if o[1] == m.group("modifier")),None)
            if not location_type:
                raise Exception("Location modifier({}) Not Support".format(m.group("modifier")))

            #check interal location
            internal_location = True if internal_location_re.search(configure_txt) else False
            if internal_location:
                #internal_location,ignore
                return None
            
            #redirect data
            redirect = None
            for location_redirect_re in location_redirect_res:
                m = location_redirect_re.search(configure_txt)
                if m:
                    redirect = configure_txt[m.start():m.end()].strip()
                    break

            #get refuse data
            refuse = False
            for location_refuse_re in location_refuse_res:
                m = location_refuse_re.search(configure_txt)
                if m:
                    refuse = True
                    break


            #get return code
            return_code = None
            m = return_re.search(configure_txt)
            if m:
                return_code = int(m.group("code"))

            #get auth type
            auto_type = None
            for auth,auth_re in sso_auth_types:
                if auth_re:
                    if auth_re.search(configure_txt):
                        auth_type = auth
                        break
                else:
                    auth_type = auth
                    break
            if location_type == WebAppLocation.PREFIX_LOCATION and location == "/sso":
                #sso authentication 
                if auth_type not in (WebAppLocation.SSO_AUTH_TO_DBCA,WebAppLocation.SSO_AUTH_TO_DPAW,WebAppLocation.SSO_AUTH_TO_UAT):
                    raise Exception("""Can't find the sso authentication type in configure
{}""".format(configure_txt))

            #cors enabled or not
            cors_enabled = True if cors_re.search(configure_txt) else False

            #forward
            forward_servers = None
            forward_protocol = None
            forward_path = None
            for protocol,protocol_re in protocol_types:
                m = protocol_re.search(configure_txt)
                if m:
                    forward_protocol = protocol
                    forward_path = m.group('path')
                    if m.group('port'):
                        forward_servers = [[m.group("server"),int(m.group("port"))]]
                    elif m.group("server") in upstream_servers:
                        forward_servers = upstream_servers[m.group("server")]
                    elif forward_protocol == WebAppLocation.HTTP:
                        forward_servers = [[m.group("server"),80]]
                    elif forward_protocol == WebAppLocation.HTTPS:
                        forward_servers = [[m.group("server"),443]]
                    else:
                        raise Exception("""Port number is not found for protocol({}), server={}, location=
{} """.format(forward_protocol,configure_txt))
                        
                    break
            if not forward_protocol and not redirect and not return_code and not refuse:
                logger.error("""Both forward and redirect are not found .server={} location=
{}
""".format(server,configure_txt))
            if forward_protocol and not forward_servers:
                raise Exception("""Missing forward servers, parse location failed.server={}  location=
{}
""".format(server,configure_txt))
            
            locations.append({
                "location":location,
                "location_type":location_type,
                "auth_type":auth_type,
                "cors_enabled":cors_enabled,
                "redirect":redirect,
                "return_code":return_code,
                "refuse":refuse,
                "forward_servers":forward_servers,
                "forward_protocol":forward_protocol,
                "forward_path":forward_path,
                "configure_txt":configure_txt
            })
        return None

    #get all variables
    for line in config_lines:
        s_line = line.strip()
        if not s_line:
            #empty line
            continue
        elif s_line.startswith("#"):
            #comments,ignore
            continue
        if s_line.startswith("set "):
            var_name,var_val = line.split()[1:3]
            if var_val[-1] == ";":
                var_val = var_val[:-1]
            variables.append((var_name,var_val))
    #split the server_config to list of listens; list of locations; list of variables 
    for line in config_lines:
        s_line = line.strip()
        if not s_line:
            #empty line
            continue
        elif s_line.startswith("#"):
            #comments,ignore
            continue
        elif s_line.startswith("redirect "):
            m = redirect_re.search(s_line)
            if m:
                redirect_to_server = m.group("target_server")
                redirect_path = m.group("path")
        elif s_line.startswith("listen "):
            location_lines = _save_location(location_lines)
            m = listen_re.search(s_line)
            if not m:
                raise Exception("Can't parse listen line({1}) for server({0})".format(server,s_line))
            
            listens.append({
                "listen_host":m.group('host'),
                "listen_port":int(m.group('port')),
                "https":True if m.group('https') else False,
                "configure_txt":s_line
            })
        elif s_line.startswith("location "):
            location_lines = _save_location(location_lines)
            location_lines = [line]
        elif s_line.startswith("set "):
            #location_lines = _save_location(location_lines)
            continue
        elif location_lines:
            location_lines.append(line)
        else:
            raise Exception("Can't parse line({1}) for server({0})".format(server,line))

    location_lines = _save_location(location_lines)

    return (redirect_to_server,redirect_path,listens,locations)



def harvest(reconsume=False):
    with LockSession(get_resource_consume_client(),3000) as lock_session:
        if not reconsume:
            #check whether some nginx configuration has been changed after last consuming.
            if get_resource_consume_client().is_behind(resources=["nginx-config.yml","nginx.yml"]):
                reconsume = True
            else:
                return 0
    
        #consume nginx config file
        return get_resource_consume_client().consume(process_nginx,resources=["nginx-config.yml","nginx.yml"],reconsume=reconsume)


