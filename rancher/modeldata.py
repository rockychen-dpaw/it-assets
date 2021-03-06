from datetime  import datetime,timedelta
import logging
import traceback

from django.db.models import F,Q
from django.conf import settings
from django.utils import timezone

from data_storage import LockSession

from . import models
from registers.models import ITSystem

logger = logging.getLogger(__name__)

def synchronize_logharvester(func):
    def _wrapper(*args,**kwargs):
        from . import podstatus_harvester
        from . import containerstatus_harvester
        from . import containerlog_harvester
        with LockSession(podstatus_harvester.get_client(),3600 * 3) as lock_session1:
            with LockSession(containerstatus_harvester.get_client(),3600 * 3) as lock_session2:
                with LockSession(containerlog_harvester.get_client(),3600 * 3) as lock_session3:
                    func(*args,**kwargs)
    return _wrapper

def _reset_workload_latestcontainers(workloads=None):
    """
    Reset the latest containers
    """
    if not workloads:
        workload_qs = models.Workload.objects.all().order_by("cluster","name")
    elif isinstance(workloads,(list,tuple)):
        if len(workloads) == 1:
            workload_qs = models.Workload.objects.filter(id=workloads[0])
        else:
            workload_qs = models.Workload.objects.filter(id__in=workloads).order_by("cluster","name")
    else:
        workload_qs = models.Workload.objects.filter(id=workloads)

    for workload in workload_qs:
        logger.debug("Begin to process models.Workload:{}({})".format(workload,workload.id))
        workload.latest_containers = None
        if workload.kind in ("Deployment",'DaemonSet','StatefulSet','service?'):
            for container in models.Container.objects.filter(cluster=workload.cluster,workload=workload,status__in=("waiting","running")).order_by("pod_created"):
                log_status = (models.Workload.INFO if container.log else 0) | (models.Workload.WARNING if container.warning else 0) | (models.Workload.ERROR if container.error else 0)
                if workload.latest_containers is None:
                    workload.latest_containers=[[container.id,1,log_status]]
                else:
                    workload.latest_containers.append([container.id,1,log_status])
        else:
            first_running_container = models.Container.objects.filter(cluster=workload.cluster,workload=workload,status__in=("waiting","running")).order_by("pod_created").first()
            if first_running_container:
                qs = models.Container.objects.filter(cluster=workload.cluster,workload=workload,pod_created__gte=first_running_container.pod_created).order_by("pod_created")
            else:
                qs= [models.Container.objects.filter(cluster=workload.cluster,workload=workload).order_by("-pod_created").first()]

            for container in qs:
                if not container:
                    continue

                log_status = (models.Workload.INFO if container.log else 0) | (models.Workload.WARNING if container.warning else 0) | (models.Workload.ERROR if container.error else 0)
                running_status = 1 if container.status in ("waiting","running") else 0
                if workload.latest_containers is None:
                    workload.latest_containers=[[container.id,running_status,log_status]]
                else:
                    workload.latest_containers.append([container.id,running_status,log_status])
        workload.save(update_fields=["latest_containers"])
        logger.debug("models.Workload({}<{}>):update latest_containers to {}".format(workload,workload.id,workload.latest_containers))

def reset_workload_latestcontainers(sync=True,workloads=None):
    if sync:
        synchronize_logharvester(_reset_workload_latestcontainers)(workloads)
    else:
        _reset_workload_latestcontainers(workloads)


def reset_project_property():
    """
    synchronize_logharvester namespace's project with the project of workload, ingress and models.PersistentVolumeClaim
    """
    #assign namespace's project to workload's project
    for obj in models.Workload.objects.filter(namespace__project__isnull=False).exclude(project=F("namespace__project")):
        obj.project = obj.namespace.project
        obj.save(update_fields=["project"])

    #set workload's project to None if namespace's project is none
    for obj in models.Workload.objects.filter(namespace__project__isnull=True).filter(project__isnull=False):
        obj.project = None
        obj.save(update_fields=["project"])

    #assign namespace's project to ingress's project
    for obj in models.Ingress.objects.filter(namespace__isnull=False,namespace__project__isnull=False).exclude(project=F("namespace__project")):
        obj.project = obj.namespace.project
        obj.save(update_fields=["project"])

    #set ingress's project to None if namespace's project is none
    for obj in models.Ingress.objects.filter(Q(namespace__isnull=True) | Q(namespace__project__isnull=True)).filter(project__isnull=False):
        obj.project = None
        obj.save(update_fields=["project"])

    #assign namespace's project to persistentvolumeclaim's project
    for obj in models.PersistentVolumeClaim.objects.filter(namespace__isnull=False,namespace__project__isnull=False).exclude(project=F("namespace__project")):
        obj.project = obj.namespace.project
        obj.save(update_fields=["project"])

    #set persistentvolumeclaim's project to None if namespace's project is none
    for obj in models.PersistentVolumeClaim.objects.filter(Q(namespace__isnull=True) | Q(namespace__project__isnull=True)).filter(project__isnull=False):
        obj.project = None
        obj.save(update_fields=["project"])


def check_project_property():
    """
    Check whether the namespace's project is the same as the project of workload, ingress and models.PersistentVolumeClaim, and print the result
    """
    objs = list(models.Workload.objects.filter(namespace__project__isnull=False).exclude(project=F("namespace__project")))
    objs += list(models.Workload.objects.filter(namespace__project__isnull=True).filter(project__isnull=False))
    if objs:
        logger.info("The following workloads'project are not equal with namespace's project.{}\n".format(["{}({})".format(o,o.id) for o in objs]))

    objs = list(models.Ingress.objects.filter(namespace__isnull=False,namespace__project__isnull=False).exclude(project=F("namespace__project")))
    objs += list(models.Ingress.objects.filter(Q(namespace__isnull=True) | Q(namespace__project__isnull=True)).filter(project__isnull=False))
    if objs:
        logger.info("The following ingresses'project are not equal with namespace's project.{}\n".format(["{}({})".format(o,o.id) for o in objs]))

    objs = list(models.PersistentVolumeClaim.objects.filter(namespace__isnull=False,namespace__project__isnull=False).exclude(project=F("namespace__project")))
    objs += list(models.PersistentVolumeClaim.objects.filter(Q(namespace__isnull=True) | Q(namespace__project__isnull=True)).filter(project__isnull=False))
    if objs:
        logger.info("The following models.PersistentVolumeClaims'project are not equal with namespace's project.{}\n".format(["{}({})".format(o,o.id) for o in objs]))

def check_workloads_property():
    """
    Check whether the active and deleted workloads is the same as the value of column 'active_workloads' and 'deleted_workloads' in model 'models.Namespace','models.Project' and 'models.Cluster' and print the result
    """
    for obj in models.Namespace.objects.all():
        active_workloads = models.Workload.objects.filter(namespace=obj,deleted__isnull=True).count()
        deleted_workloads = models.Workload.objects.filter(namespace=obj,deleted__isnull=False).count()
        if obj.active_workloads != active_workloads or obj.deleted_workloads != deleted_workloads:
            logger.info("models.Namespace({}<{}>): active_workloads={}, expected acrive_workloads={}; deleted_workloads={}, expected deleted_workloads={}".format(
                obj,
                obj.id,
                obj.active_workloads,
                active_workloads,
                obj.deleted_workloads,
                deleted_workloads
            ))


    for obj in models.Project.objects.all():
        active_workloads = models.Workload.objects.filter(namespace__project=obj,deleted__isnull=True).count()
        deleted_workloads = models.Workload.objects.filter(namespace__project=obj,deleted__isnull=False).count()
        if obj.active_workloads != active_workloads or obj.deleted_workloads != deleted_workloads:
            logger.info("models.Project({}<{}>): active_workloads={}, expected acrive_workloads={}; deleted_workloads={}, expected deleted_workloads={}".format(
                obj,
                obj.id,
                obj.active_workloads,
                active_workloads,
                obj.deleted_workloads,
                deleted_workloads
            ))

    for obj in models.Cluster.objects.all():
        active_workloads = models.Workload.objects.filter(cluster=obj,deleted__isnull=True).count()
        deleted_workloads = models.Workload.objects.filter(cluster=obj,deleted__isnull=False).count()
        if obj.active_workloads != active_workloads or obj.deleted_workloads != deleted_workloads:
            logger.info("models.Cluster({}<{}>): active_workloads={}, expected acrive_workloads={}; deleted_workloads={}, expected deleted_workloads={}".format(
                obj,
                obj.id,
                obj.active_workloads,
                active_workloads,
                obj.deleted_workloads,
                deleted_workloads
            ))

def reset_workloads_property():
    """
    Update the column 'active_workoads' and 'deleted_workloads' in model 'models.Namespace', 'models.Project' and 'models.Cluster' to the active workloads and deleted workloads

    """
    for obj in models.Namespace.objects.all():
        active_workloads = models.Workload.objects.filter(namespace=obj,deleted__isnull=True).count()
        deleted_workloads = models.Workload.objects.filter(namespace=obj,deleted__isnull=False).count()
        if obj.active_workloads != active_workloads or obj.deleted_workloads != deleted_workloads:
            logger.info("models.Namespace({}<{}>): active_workloads={}, expected acrive_workloads={}; deleted_workloads={}, expected deleted_workloads={}".format(
                obj,
                obj.id,
                obj.active_workloads,
                active_workloads,
                obj.deleted_workloads,
                deleted_workloads
            ))
            obj.active_workloads = active_workloads
            obj.deleted_workloads = deleted_workloads
            obj.save(update_fields=["active_workloads","deleted_workloads"])


    for obj in models.Project.objects.all():
        active_workloads = models.Workload.objects.filter(namespace__project=obj,deleted__isnull=True).count()
        deleted_workloads = models.Workload.objects.filter(namespace__project=obj,deleted__isnull=False).count()
        if obj.active_workloads != active_workloads or obj.deleted_workloads != deleted_workloads:
            logger.info("models.Project({}<{}>): active_workloads={}, expected acrive_workloads={}; deleted_workloads={}, expected deleted_workloads={}".format(
                obj,
                obj.id,
                obj.active_workloads,
                active_workloads,
                obj.deleted_workloads,
                deleted_workloads
            ))
            obj.active_workloads = active_workloads
            obj.deleted_workloads = deleted_workloads
            obj.save(update_fields=["active_workloads","deleted_workloads"])

    for obj in models.Cluster.objects.all():
        active_workloads = models.Workload.objects.filter(cluster=obj,deleted__isnull=True).count()
        deleted_workloads = models.Workload.objects.filter(cluster=obj,deleted__isnull=False).count()
        if obj.active_workloads != active_workloads or obj.deleted_workloads != deleted_workloads:
            logger.info("models.Cluster({}<{}>): active_workloads={}, expected acrive_workloads={}; deleted_workloads={}, expected deleted_workloads={}".format(
                obj,
                obj.id,
                obj.active_workloads,
                active_workloads,
                obj.deleted_workloads,
                deleted_workloads
            ))
            obj.active_workloads = active_workloads
            obj.deleted_workloads = deleted_workloads
            obj.save(update_fields=["active_workloads","deleted_workloads"])


def _clean_containers():
    """
    clean all containers and container logs,
    sync projects and workloads
    """
    reset_workloads_property()
    models.ContainerLog.objects.all().delete()
    models.Container.objects.all().delete()
    models.Workload.objects.filter(added_by_log=True).delete()
    models.Namespace.objects.filter(added_by_log=True).delete()
    models.Cluster.objects.filter(added_by_log=True).delete()
    models.Workload.objects.all().update(deleted=None,latest_containers=None)
    reset_project_property()
    reset_workloads_property()

def clean_containers(sync=True):
    if sync:
        synchronize_logharvester(_clean_containers)()
    else:
        _clean_containers()


def _clean_containerlogs():
    """
    Clear all container logs
    """
    models.ContainerLog.objects.all().delete()
    models.Container.objects.all().update(log=False,warning=False,error=False)
    for workload in models.Workload.objects.all():
        if workload.latest_containers:
            for container in workload.latest_containers:
                container[2] = 0
            workload.save(update_fields=["latest_containers"])

def clean_containerlogs(sync=True):
    if sync:
        synchronize_logharvester(_clean_containerlogs)()
    else:
        _clean_containerlogs()


def clean_added_by_log_data():
    """
    Clean all the data which is added by log
    """
    deleted_rows = models.ContainerLog.objects.filter(container__workload__added_by_log=True).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = models.Container.objects.filter(workload__added_by_log=True).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))

    deleted_rows = models.Ingress.objects.filter(namespace__added_by_log=True).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))

    deleted_rows = models.Workload.objects.filter(added_by_log=True).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))

    deleted_rows = models.PersistentVolume.objects.filter(cluster__added_by_log=True).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = models.PersistentVolumeClaim.objects.filter(cluster__added_by_log=True).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = models.ConfigMap.objects.filter(namespace__added_by_log=True).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))

    deleted_rows = models.Namespace.objects.filter(added_by_log=True).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = models.Project.objects.filter(cluster__added_by_log=True).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = models.Cluster.objects.filter(added_by_log=True).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))


def clean_expired_deleted_data():
    logger.info("Begin to clean expired deleted data")
    expired_time = timezone.now() - settings.DELETED_RANCHER_OBJECT_EXPIRED
    deleted_rows = models.ContainerLog.objects.filter(container__workload__deleted__lt=expired_time).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = models.Container.objects.filter(workload__deleted__lt=expired_time).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))

    deleted_rows = models.Ingress.objects.filter(deleted__lt=expired_time).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = models.Workload.objects.filter(deleted__lt=expired_time).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))


    deleted_rows = models.PersistentVolumeClaim.objects.filter(volume__deleted__lt=expired_time).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))

    deleted_rows = models.PersistentVolume.objects.filter(deleted__lt=expired_time).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = models.Namespace.objects.filter(deleted__lt=expired_time).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))


def clean_expired_containers(cluster=None):
    """
    delete the expired containers from database to improve performance
    """
    if cluster:
        if isinstance(cluster,models.Cluster):
            cluster_qs = [cluster]
        else:
            try:
                cluster_qs = models.Cluster.objects.filter(id=int(cluster))
            except:
                cluster_qs = models.Cluster.objects.filter(name=str(cluster))
    else:
        cluster_qs = models.Cluster.objects.all().order_by("name")

    for cluster in cluster_qs:
        logger.info("Begin to clean expired containers of workloads in cluster({})".format(cluster))
        for workload in models.Workload.objects.filter(cluster=cluster).order_by("id"):
            logger.debug("Begin to clean expired containers for workload({})".format(workload))
            earliest_running_container = models.Container.objects.filter(cluster=cluster,workload=workload).filter(status__in=("running","waiting")).order_by("pod_created").first()
            if earliest_running_container:
                #found a running container
                non_expired_qs = models.Container.objects.filter(cluster=cluster,workload=workload,pod_created__lt=earliest_running_container.pod_created).order_by("-pod_created")[:settings.RANCHER_CONTAINERS_PER_WORKLOAD]
            else:
                non_expired_qs = models.Container.objects.filter(cluster=cluster,workload=workload).order_by("-pod_created")[:settings.RANCHER_CONTAINERS_PER_WORKLOAD]

            if non_expired_qs.count() < settings.RANCHER_CONTAINERS_PER_WORKLOAD:
                #all containers are not expired
                continue
            non_expired_ids = [o.id for  o in non_expired_qs]
            if earliest_running_container:
                deleted_rows = models.Container.objects.filter(cluster=cluster,workload=workload,pod_created__lt=earliest_running_container.pod_created).exclude(id__in=non_expired_ids).delete()
            else:
                deleted_rows = models.Container.objects.filter(cluster=cluster,workload=workload).exclude(id__in=non_expired_ids).delete()
            logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))


def clean_expired_containerlogs():
    expired_time = timezone.now() - settings.RANCHER_CONTAINERLOG_EXPIRED
    
    deleted_rows = models.ContainerLog.objects.filter(logtime__lt=expired_time).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))


def delete_cluster(idorname):
    """
    delete cluster
    """
    try:
        cluster = models.Cluster.objects.get(id=int(idorname))
    except:
        cluster = models.Cluster.objects.get(name=str(idorname))

    deleted_rows = models.ContainerLog.objects.filter(container__cluster=cluster).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = models.Container.objects.filter(cluster=cluster).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))

    deleted_rows = models.Workload.objects.filter(cluster=cluster).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))

    deleted_rows = models.Ingress.objects.filter(cluster=cluster).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = models.PersistentVolumeClaim.objects.filter(cluster=cluster).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = models.PersistentVolume.objects.filter(cluster=cluster).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = models.ConfigMap.objects.filter(cluster=cluster).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))

    deleted_rows = models.Namespace.objects.filter(cluster=cluster).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = models.Project.objects.filter(cluster=cluster).delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))
    deleted_rows = cluster.delete()
    logger.info("Delete {} objects. {}".format(deleted_rows[0]," , ".join( "{}={}".format(k,v) for k,v in deleted_rows[1].items())))


def clean_orphan_projects(cluster = None):
    """
    cluster can be 
      1. None: means all clusters
      2. models.Cluster instance
      3. models.Cluster id
      4. models.Cluster name
    """
    logger.info("Begin to clean orphan projects")
    if cluster:
        if isinstance(cluster,models.Cluster):
            qs = models.Project.objects.filter(cluster=cluster)
        else:
            try:
                qs = models.Project.objects.filter(cluster__id=int(cluster))
            except:
                qs - models.Project.objects.filter(cluster__name=cluster)
    else:
        qs = models.Project.objects.all()

    deleted_projects = []
    for project in qs:
        exists = False
        for cls in (models.Namespace,models.PersistentVolumeClaim,models.Ingress,models.Workload):
            if cls.objects.filter(project=project).exists():
                exists = True
                break
        if not exists:
            deleted_projects.append(project)


    if deleted_projects:
        logger.info("There are {} orphan projects,({}). try to delete them ".format(len(deleted_projects)," , ".join(str(p) for p in deleted_projects)))
        for project in deleted_projects:
            project.delete()
    else:
        logger.info("No orphan projects are found.")


def clean_orphan_namespaces(cluster = None):
    """
    cluster can be 
      1. None: means all clusters
      2. models.Cluster instance
      3. models.Cluster id
      4. models.Cluster name
    """
    logger.info("Begin to clean orphan namespaces")
    if cluster:
        if isinstance(cluster,models.Cluster):
            qs = models.Namespace.objects.filter(cluster=cluster)
        else:
            try:
                qs = models.Namespace.objects.filter(cluster__id=int(cluster))
            except:
                qs - models.Namespace.objects.filter(cluster__name=cluster)
    else:
        qs = models.Namespace.objects.all()

    deleted_namespaces = []
    for namespace in qs:
        exists = False
        for cls in (models.ConfigMap,models.PersistentVolumeClaim,models.Ingress,models.Workload,models.Container):
            if cls.objects.filter(namespace=namespace).exists():
                exists = True
                break
        if not exists:
            deleted_namespaces.append(namespace)


    if deleted_namespaces:
        logger.info("There are {} orphan namespaces,({}). try to delete them ".format(len(deleted_namespaces)," , ".join(str(p) for p in deleted_namespaces)))
        for namespace in deleted_namespaces:
            namespace.delete()
    else:
        logger.info("No orphan namespaces are found.")

def clean_unused_oss():
    for obj in list(models.OperatingSystem.objects.filter(images=0)):
        try:
            obj.delete()
        except:
            logger.error("Failed to delete unused operating system({}).{}".format(obj,traceback.format_exc()))


def clean_unreferenced_vulnerabilities():
    for vuln in models.Vulnerability.objects.filter(affected_images__lt=1):
        count = vuln.containerimage_set.all().count()
        if count > 0:
            logger.error("There are {2} images reference the vulnerability({0}), but the affected_images is {1}, update it to {2} ".format(vuln,vuln.affected_images,count))
            vuln.affected_images = count
            vuln.save(update_fields=["affected_images"])
        else:
            try:
                vuln.delete()
            except:
                logger.error("Failed to delete unreferenced vulnerability({}).{}".format(vuln,traceback.format_exc()))

def clean_unreferenced_images():
    for img in models.ContainerImage.objects.filter(workloads__lt=1):
        count = models.Workload.objects.filter(containerimage=img).count()
        if count > 0:
            logger.error("There are {2} workloads reference the image({0}), but the workoads is {1}, update it to {2} ".format(img,img.workloads,count))
            img.workloads = count
            img.save(update_fields=["workloads"])
        else:
            try:
                img.delete()
            except:
                logger.error("Failed to delete unreferenced image({}).{}".format(img,traceback.format_exc()))

def check_aborted_harvester():
    now = timezone.now()
    abort_time = now - settings.HARVESTER_ABORTED
    models.Harvester.objects.filter(status=models.Harvester.RUNNING,last_heartbeat__lt=abort_time).update(status=models.Harvester.ABORTED,message="Harvester exited abnormally.",endtime=now)

def clean_expired_harvester():
    expired_time = timezone.now() - settings.HARVESTER_EXPIRED
    models.Harvester.objects.filter(starttime__lt=expired_time).delete()


def reparse_image_scan_result(scan=False):
    models.ContainerImage.objects.all().update(os=None)
    models.ContainerImage.objects.filter(scan_result__isnull=False).update(scan_status=models.ContainerImage.PARSE_FAILED)
    models.Vulnerability.objects.all().delete()
    models.OperatingSystem.objects.all().delete()

    qs = models.ContainerImage.objects.all()
    if not scan:
        qs = qs.filter(scan_result__isnull=False)
    for image in qs:
        image.scan(rescan=False,reparse=True)
        print("Succeed to parse the scan result of the container image '{}'".format(image.imageid))

def set_workload_itsystem(refresh=False):
    itsystems = list(ITSystem.objects.all().only("name","acronym","extra_data"))

    qs = models.Workload.objects.all()
    if not refresh:
        qs = qs.filter(itsystem__isnull=True)

    #update deployment first
    for workload in qs.filter(kind=models.Workload.DEPLOYMENT):
        print("Begin to update the itsystem({2}) of the workload({0}<{1}>)".format(workload,workload.id,workload.itsystem))
        if workload.update_itsystem(itsystems=itsystems,refresh=refresh):
            print("Update the itsystem of the workload({0}) to {1}".format(workload,workload.itsystem))
        else:
            print("The itsystem({1}) of the workload({0}) is not changed".format(workload,workload.itsystem))


    #update others
    for workload in qs.exclude(kind=models.Workload.DEPLOYMENT):
        print("Begin to update the itsystem({2}) of the workload({0}<{1}>)".format(workload,workload.id,workload.itsystem))
        if workload.update_itsystem(itsystems=itsystems,refresh=refresh):
            print("Update the itsystem of the workload({0}) to {1}".format(workload,workload.itsystem))
        else:
            print("The itsystem({1}) of the workload({0}) is not changed".format(workload,workload.itsystem))
