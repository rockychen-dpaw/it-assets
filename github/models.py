import os
import traceback
import imp
import re
import subprocess
from datetime import datetime,timedelta
import logging
import tempfile

import requests

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError,ObjectDoesNotExist
from django.db.models.signals import post_save,pre_save,pre_delete
from django.dispatch import receiver
from django.db.models import Q

from django.contrib.postgres.fields import ArrayField

logger = logging.getLogger(__name__)

WAITING=1
SYNCING=2
SCANING=3
FAILED=4
STATUS_CHOICES = (
    (WAITING,"Waiting"),
    (SYNCING,"Syncing"),
    (SCANING,"Scaning"),
    (FAILED,"Failed")
)

# Create your models here.
class Account(models.Model):
    name = models.CharField(max_length=64,unique=True,null=False)
    parent = models.ForeignKey("self", on_delete=models.PROTECT,null=True,blank=True,related_name="children")
    managed = models.BooleanField(default=True,editable=False)
    active = models.BooleanField(default=True)
    last_actived= models.DateTimeField(auto_now_add=True)

    organization = models.BooleanField(default=False,editable=True)
    synced = models.BooleanField(default=False,editable=False)

    last_synced = models.DateTimeField(null=True,editable=False)
    added = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.parent == self:
            raise ValidationError("Account's parent can't be itself.")

    def sync(self,force=False):
        if not self.active:
            #not active. no need to sync
            return
        if force or not self.synced:
            self._sync_user(force)
            self._sync_repository(force)
            self.synced = True
            self.last_synced = timezone.now()
            self.save(update_fields=["synced","last_synced"])

    def _sync_user(self,force):
        if not self.organization:
            #user has no members.
            return

        res = requests.get("https://api.github.com/orgs/{}/members".format(self.name))
        res.raise_for_status()
        users = res.json()
        for user in users:
            account,created = Account.objects.get_or_create(
                parent=self,
                name=user["login"],
                defaults={
                    'organization':False,
                    'synced':False,
                    'managed':False
                }
            )
            if created:
                #new user, automatically sync this user.
                account.sync(force=force)
        

    
    def _sync_repository(self,force):
        #sync the repository from github
        if self.organization:
            res = requests.get("https://api.github.com/orgs/{}/repos".format(self.name))
        else:
            res = requests.get("https://api.github.com/users/{}/repos".format(self.name))
        res.raise_for_status()
        repos = res.json()
        repositories = []
        for repo in repos:
            repository,created = Repository.objects.get_or_create(
                name=repo["name"],
                account=self,
                defaults={
                    'private':repo['private'],
                    'synced':False,
                    'scaned':False,
                    'managed':False,
                    'active':True,
                    'last_actived':timezone.now()
                }
            )
            """
            if not created and not repository.active:
                #repository is not active, change it to active
                repository.active = True
                repository.last_actived = timezone.now()
                repository.save(update_fields=["active","last_actived"])
            """
            repositories.append(repository.id)

            #let the task sync repository
            #repository.sync(force=force)

        #deactive the repositories which is deleted from user
        Repository.objects.filter(account=self,managed=False).exclude(id__in=repositories).update(active=False,last_actived=timezone.now())

        #let the task sync repository
        #for repo in Repository.objects.filter(account=self,managed=True):
        #    repo.sync(force=force)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ('organization','name',)


class Repository(models.Model):
    _master_branch = None
    name = models.CharField(max_length=128,null=False)
    account = models.ForeignKey(Account, on_delete=models.PROTECT,null=False,related_name="repositories")
    private = models.BooleanField(default=False)
    managed = models.BooleanField(default=True,editable=False)
    synced = models.BooleanField(default=False,editable=False)
    last_synced = models.DateTimeField(null=True,editable=False)
    scaned = models.BooleanField(default=False,editable=False)

    active = models.BooleanField(default=True)
    last_actived= models.DateTimeField(auto_now_add=True)

    process_status = models.SmallIntegerField(choices=STATUS_CHOICES,editable=False,default=WAITING)
    process_message = models.TextField(null=True,editable=False)
    last_process_start = models.DateTimeField(null=True,editable=False)
    last_process_end = models.DateTimeField(null=True,editable=False)
    
    @property
    def master_branch(self):
        if not self._master_branch:
            self._master_branch = Branch.objects.get(repository=self,name="master")

        return self._master_branch

    def sync(self,force=False):
        if not self.account.active or not self.active: 
            #owner is not active, no need sync
            return
        if self._lock(SYNCING):
            try:
                self._sync(force)
                self._release_lock()
            except:
                self._release_lock(False,traceback.format_exc())
                raise

    def _sync(self,force):
        if force or not self.synced:
            self._sync_code()
            self._sync_branches()
            self.synced = True
            self.last_synced = timezone.now()
            self.save(update_fields=["synced","last_synced"])

    @classmethod
    def scan_leak(cls,count=20):
        repo = None
        #find a repositories to sync
        repo_qs = Repository.objects.filter(account__active=True,active=True).order_by("id")
        while not repo:
            repo = repo_qs.filter(synced=False,process_status=WAITING).first()

            if not repo:
                repo = repo_qs.filter(synced=True,last_synced__lt=timezone.now() - timedelta(hours=10),process_status=WAITING).first()

            if not repo:
                repo = repo_qs.filter(synced=False,process_status__in=[SYNCING,SCANING],last_process_start__lt = timezone.now() - timedelta(hours=2)).first()

            if not repo:
                repo = repo_qs.filter(synced=True,last_synced__lt=timezone.now() - timedelta(hours=10),process_status__in=[SYNCING,SCANING],last_process_start__lt = timezone.now() - timedelta(hours=2)).first()
                
            if not repo:
                repo = repo_qs.filter(synced=False,process_status=FAILED).first()

            if not repo:
                repo = repo_qs.filter(synced=True,process_status=FAILED,last_synced__lt=timezone.now() - timedelta(hours=10)).first()

            if repo:
                if not repo._lock(SYNCING):
                    repo = None
            else:
                break

        if repo:
            try:
                logger.debug("Begin to sync the repository({})".format(repo))
                repo._sync(True)
                repo._release_lock()
            except:
                repo._release_lock(False,traceback.format_exc())

            if repo.process_status == FAILED:
                return "Failed to sync repository({}) from {} to {}.{}".format(repo,repo.last_process_start,repo.last_process_end,repo.process_message)
            else:
                return "Succeed to sync repository({}) from {} to {}.{}".format(repo,repo.last_process_start,repo.last_process_end,repo.process_message)
            return


        #find a repositories to scan
        branch = None
        branch_qs = Branch.objects.filter(
            repository__account__active=True,
            repository__active=True,
            synced=True,
            scaned=False,
            active=True).order_by("repository__account__name","repository__name","name")
        #always scan master branch first
        master_branch_qs = branch_qs.filter(name="master")
        while not repo:
            #scan organization's repository first
            #try to find a repository which is in [waiting,failed] status to sync or scan
            #scan master first
            branch = master_branch_qs.filter(repository__process_status=WAITING).first()
            if not branch:
                branch = master_branch_qs.filter(repository__process_status__in=[SYNCING,SCANING],repository__last_process_start__lt = timezone.now() - timedelta(hours=2)).first()
            if not branch:
                branch = master_branch_qs.filter(repository__process_status=FAILED).first()

            if branch:
                repo = branch.repository
                if not repo._lock(SCANING):
                    branch = None
                    repo = None
            else:
                break

        if not repo :
            #try to find a non master branch to scan
            non_master_branch_qs = branch_qs.exclude(name="master")
            while not repo:
                #scan organization's repository first
                #try to find a repository which is in [waiting,failed] status to sync or scan
                #scan master first
                for b in non_master_branch_qs.filter(repository__process_status=WAITING):
                    if b.master_branch.scaned:
                        branch = b
                        break

                if not branch:
                    for b in non_master_branch_qs.filter(repository__process_status__in=[SYNCING,SCANING],repository__last_process_start__lt = timezone.now() - timedelta(hours=2)):
                        if b.master_branch.scaned:
                            branch = b
                            break

                if not branch:
                    for b in non_master_branch_qs.filter(repository__process_status=FAILED):
                        if b.master_branch.scaned:
                            branch = b
                            break
    
                if branch:
                    repo = branch.repository
                    if not repo._lock(SCANING):
                        branch = None
                        repo = None
                else:
                    break

        if repo:
            #found one repository
            try:
                logger.debug("Begin to scan the branch({})".format(branch))
                branch.scan(count)
                repo._release_lock()
            except:
                repo._release_lock(False,traceback.format_exc())


            if repo.process_status == FAILED:
                return "Failed to scan branch({}) from {} to {}.{}".format(branch,repo.last_process_start,repo.last_process_end,repo.process_message)
            else:
                return "Succeed to scan branch({}) from {} to {}".format(branch,repo.last_process_start,repo.last_process_end)
        else:
            return "All repositories are synced&scaned "

    def _release_lock(self,succeed=True,message=None):
        if succeed:
            self.process_message = message
            self.process_status = WAITING
        else:
            self.process_message = message
            self.process_status = FAILED
        self.last_process_end = timezone.now()
        self.save(update_fields=["process_status","process_message","last_process_end"])

    def _lock(self,status):
        """
        get a lock before scaning or syncing
        status can be SYNCING ,SCANING
        Return True if get a lock ;otherwise return False
        """
        now = timezone.now()
        if self.process_status in [SYNCING,SCANING]:
            if self.last_process_start <= timezone.now() - timedelta(hours=2):
                repo_qs = Repository.objects.filter(pk=self.pk,process_status=self.process_status,last_process_start=self.last_process_start)
            else:
                return False
        else:
            repo_qs = Repository.objects.filter(pk=self.pk,process_status=self.process_status)

        if repo_qs.update(process_status=status,last_process_start=now,last_process_end=None,process_message=None):
            self.process_status = status
            self.last_process_start=now
            self.last_proces_end=None
            self.process_message = None
            return True
        else:
            return False

    def repository_file_path(self,file_path):
        if file_path.startswith(self.local_repo_folder):
            return file_path[len(self.local_repo_folder):]
        else:
            return file_path

    def file_path(self,repository_file_path):
        if repository_file_path.startswith("/"):
            return os.path.join(self.local_repo_folder,repository_file_path[1:])
        else:
            return os.path.join(self.local_repo_folder,repository_file_path)


    @property
    def local_repo_folder(self):
        if not hasattr(self,"_local_repo_folder"):
            #create the user folder if not exist
            user_folder =os.path.join(settings.REPOSITORY_ROOT,self.account.name)
            if not os.path.exists(user_folder):
                os.mkdir(user_folder)
            self._local_repo_folder = os.path.join(user_folder,self.name)

        return self._local_repo_folder

    @property
    def repo_url(self):
        return "https://github.com/{}/{}".format(self.account.name,self.name)

    @property
    def is_cloned(self):
        return os.path.exists(os.path.join(self.local_repo_folder,".git"))

    def _sync_code(self):
        if self.is_cloned:
            subprocess.check_call("cd {} && git stash -u && git stash clear && git checkout master && git fetch".format(self.local_repo_folder),shell=True)
            #subprocess.check_call("cd {} && git checkout master && git fetch".format(self.local_repo_folder),shell=True)
        else:
            subprocess.check_call("git clone {} {}".format(self.repo_url,self.local_repo_folder),shell=True)

    def _sync_branches(self):
        #fetch the latest code and remove non existing remote branch
        subprocess.check_output("cd {} && git fetch origin && git remote prune origin".format(self.local_repo_folder),shell=True)

        #list all the branches
        branches = subprocess.check_output("cd {} && git branch -r".format(self.local_repo_folder),shell=True)
        #branch list, pattern: origin/HEAD or origin/HEAD -> origin/maste
        branches = [b.strip() for b in branches.decode().split(os.linesep) if b.strip()]

        branchids = []
        index = len(branches) - 1
        while index >= 0:
            b = branches[index]
            branch_data = b.split("->")
            if len(branch_data)  == 2 :
                #this is a branche reference to another branch, ignore
                del branches[index]
            elif len(branch_data) != 1:
                raise Exception("Can't parse branch data({}) for repository({})".format(b,self))
            else:
                branches[index] = branch_data[0].split("/",1)[1].strip()
            index -= 1

        try:
            master_index = branches.index("master")
            if master_index >= 0:
                del branches[master_index]
                branches.insert(0,"master")
            else:
                raise Exception("Can't find master branch in repository({})".format(self))
        except:
            raise Exception("Can't find master branch in repository({})".format(self))


        local_branches = subprocess.check_output("cd {} && git branch --list".format(self.local_repo_folder),shell=True)
        #branch list, pattern: origin/HEAD or origin/HEAD -> origin/maste
        local_branches = [b.strip().lstrip('*').strip() for b in local_branches.decode().split(os.linesep) if b.strip()]

        for b in branches:
            branch,created = Branch.objects.get_or_create(
                name = b,
                repository = self
            )
            if b not in local_branches:
                #create the local branch
                subprocess.check_call("cd {0} && git stash -u && git stash clear && git checkout -t origin/{1}".format(self.local_repo_folder,b),shell=True)
                #subprocess.check_call("cd {0} && git checkout -t origin/{1}".format(self.local_repo_folder,b),shell=True)

            if not created and not branch.active:
                branch.active = True
                branch.last_actived = timezone.now()
                branch.save(update_fields=["active","last_actived"])
            branchids.append(branch.id)
            branch.sync()

        #set active to false for removed branches
        Branch.objects.filter(repository=self).exclude(id__in=branchids).update(active=False,last_actived=timezone.now())
        #reset repository's scan status if necessary
        if not Branch.objects.filter(repository=self,scaned=False,active=True).exists():
            if not self.scaned:
                self.scaned = True
                if self.process_status == FAILED:
                    self.process_status = WAITING
                    self.process_message = None
                    self.last_process_start = None
                    self.last_process_end = None
                    self.save(update_fields=["scaned","process_status","process_message","last_process_start","last_process_end"])
                else:
                    self.save(update_fields=["scaned"])
        else:
            if self.scaned:
                self.scaned = False
                self.save(update_fields=["scaned"])

            

    def __str__(self):
        return "{}/{}".format(self.account.name,self.name)


    class Meta:
        unique_together = ('account', 'name')
        ordering = ('account','name')

class ScanContent(object):
    def __init__(self,commit,previous_commit,file_name,file_path):
        self.commit = commit
        self.previous_commit = previous_commit
        self.file_name = file_name
        self.file_path = file_path
        self.repository_file_path = self.commit.repository.repository_file_path(file_path)



    def chunks(self):
        """
        Return a iterable object. each object is a 3 length tuple
            ( 
                (the line number of the src file's first line,src file content ),
                (the line number of the target file's first line(1 based) ,target file content),
                mode, can be update or add
        """
        pass

BINARY_FILE = 1
TEXT_FILE = 2
EMPTY_FILE = 3
def file_type(file_path):
    mime_type = subprocess.check_output("file -b --mime-type \"{}\"".format(file_path),shell=True).decode().strip()
    if mime_type == 'inode/x-empty':
        return EMPTY_FILE

    mime_type = [t.strip() for t in mime_type.split("/") if t.strip()]
    for t in mime_type:
        if t in ["text","xml","json","python","ecmascript"]:
            return TEXT_FILE

    return BINARY_FILE

class FileScanContent(ScanContent):
    def __init__(self,commit,previous_commit,file_name,file_path):
        super().__init__(commit,previous_commit,file_name,file_path)
        self._content = None

    def chunks(self):
        if self._content is None:
            try:
                with open(self.file_path,'r') as f:
                    self._content = f.read()
            except Exception as ex:
                logger.warning("{}.file = {}".format(str(ex),self.file_path))
                return []

        return [((0,None),(1,self._content),"add")]

class BinaryFileScanContent(ScanContent):
    def __init__(self,commit,previous_commit,file_name,file_path):
        super().__init__(commit,previous_commit,file_name,file_path)

    def chunks(self):
        return None

class DeletedFileScanContent(ScanContent):
    def __init__(self,commit,previous_commit,file_name,file_path):
        super().__init__(commit,previous_commit,file_name,file_path)

    def chunks(self):
        return None


class FileDiffScanContent(ScanContent):
    def __init__(self,commit,previous_commit,file_name,file_path):
        super().__init__(commit,previous_commit,file_name,file_path)
        self._chunks = []

    def add_chunk(self,src_base_line_number,src_chunk,target_base_line_number,target_chunk,mode="update"):
        """
        mode: update or add
        """
        self._chunks.append(((src_base_line_number,src_chunk),(target_base_line_number,target_chunk),mode))

    def chunks(self):
        return self._chunks

    def __str__(self):
        string = """
========================FileDiffScanContent==============================================
Previouse commit={}
Commit = {}
File = {}
        """.format(self.previous_commit,self.commit,self.repository_file_path)

        index = 0
        for chunk in self.chunks():
            index += 1
            string += """
-------------Diff Chunk {}-------------------------
mode = {}
Source File Base Line Number = {}
{}
*************************************************
Target File Base Line Number = {}
{}
*************************************************
            """.format(index,chunk[2],chunk[0][0],chunk[0][1],chunk[1][0],chunk[1][1])

        return string


class Branch(models.Model):
    _master_branch = None

    name = models.CharField(max_length=256,editable=False)
    repository = models.ForeignKey(Repository, on_delete=models.PROTECT,null=False,related_name="branches")
    #first commit for master branch, the last commom commit for other branch
    base_commit = models.ForeignKey("Commit", on_delete=models.SET_NULL,null=True,editable=False,related_name="+")
    last_commit = models.ForeignKey("Commit", on_delete=models.SET_NULL,null=True,editable=False,related_name="+")

    active = models.BooleanField(default=True)
    last_actived= models.DateTimeField(auto_now_add=True)

    synced = models.BooleanField(default=False,editable=False)
    last_synced = models.DateTimeField(null=True,editable=False)

    scaned = models.BooleanField(default=False,editable=False)
    last_scaned_commit = models.ForeignKey("Commit", on_delete=models.SET_NULL,null=True,editable=False,related_name="+")
    last_scaned = models.DateTimeField(null=True,editable=False)


    @property
    def master_branch(self):
        if self.name == "master":
            return self
        elif not self._master_branch:
            self._master_branch = Branch.objects.get(repository=self.repository,name="master")

        return self._master_branch

    @property
    def is_master_branch(self):
        return self.name == 'master'

    def sync(self):
        if not self.repository.account.active or not self.repository.active or not self.active:
            #not active, no need sync
            return

        self._sync_commits()
        self.synced = True
        self.last_synced = timezone.now()
        self.save(update_fields=["synced","last_synced"])

    commit_re = re.compile("^\s*(?P<commit_id>[a-zA-Z0-9_\-\+]{35,})\s*\n\s*(Merge\s*\:\s*(?P<merge>[a-zA-Z0-9_\-\+ ]+)\s*\n\s*)?Author\s*\:\s*(?P<author>[\S ]+)\s*\n\s*Date\s*\:\s*(?P<date>[a-zA-Z0-9 \.\+\:\-]+)\s*(\n\s*(?P<comments>.+))?$",re.DOTALL)
    commit_date_patterns = ['%a %b %d %H:%M:%S %Y %z','%a %b %d %H:%M:%S %Y-%z']
    def _sync_commits(self):
        #if self.name == 'disturbance':
        #    import ipdb;ipdb.set_trace()

        cmd = "cd {} && git stash -u && git stash clear && git checkout {} && git pull".format(self.repository.local_repo_folder,self.name)
        logger.debug("run cmd {}".format(cmd))
        subprocess.check_call(cmd,shell=True)
        last_synced_commit = Commit.objects.filter(repository=self.repository,branch=self).order_by("-id").first()
        if last_synced_commit:
            cmd = "cd {} && git log --since \"{}\"".format(self.repository.local_repo_folder,last_synced_commit.committed.strftime("%Y-%m-%dT%H:%M:00"))
        else:
            cmd = "cd {} && git log".format(self.repository.local_repo_folder)
        logger.debug("run cmd {}".format(cmd))
        commits = subprocess.check_output(cmd,shell=True)
        if last_synced_commit:
            with open('/tmp/tmp_{}_{}_{}_commits.{}.txt'.format(self.repository.account.name,self.repository.name.replace("/","-"),self.name.replace("/","-"),last_synced_commit.committed.strftime("%Y%m%dT%H%M00")),'wb') as f:
                f.write(commits)
        else:
            with open('/tmp/tmp_{}_{}_{}_commits.txt'.format(self.repository.account.name,self.repository.name.replace("/","-"),self.name.replace("/","-")),'wb') as f:
                f.write(commits)
        commits = "\n{}".format(commits.decode().strip())
        commits = [c.strip() for c in commits.split("\ncommit") if c.strip()]
        last_existing_commit = None
        first_create = True
        commit = None

        #if self.name == "mooring":
        #    import ipdb;ipdb.set_trace()
        
        for c in reversed(commits):
            #print("======================================")
            #print(c)
            m = self.commit_re.search(c)
            if not m:
                raise Exception("Failed to parse commit.{}".format(c))

            try:
                committed = None
                for p in self.commit_date_patterns:
                    try:
                        committed = datetime.strptime(m.group('date'),p)
                    except:
                        pass
                if not committed:
                    raise Exception("Failed to parse the committed date:{}".format(m.group('date')))

                commit,created = Commit.objects.get_or_create(
                    commit_id = m.group('commit_id'),
                    repository = self.repository,
                    branch = self,
                    defaults = {
                        "merge":m.group("merge"),
                        "comments":m.group('comments') or "",
                        "author":m.group('author'),
                        "committed":committed
                    }
                )
            except Exception as ex:
                raise ex.__class__("{}.commit = {}".format(str(ex),c))
            if created:
                if first_create:
                    first_create = False
                    if not last_existing_commit and last_synced_commit:
                        #find the previous commit of the first squshed commit
                        before_commits_cmd = "cd {} && git log --before \"{}\"".format(self.repository.local_repo_folder,last_synced_commit.committed.strftime("%Y-%m-%dT%H:%M:00"))
                        logger.debug("run cmd {}".format(before_commits_cmd))
                        before_commits = subprocess.check_output(before_commits_cmd,shell=True)
                        before_commits = "\n{}".format(before_commits.decode().strip())
                        before_commits = [c.strip() for c in before_commits.split("\ncommit") if c.strip()]
                        for before_commit in before_commits:
                            last_existing_commit = Commit.objects.filter(
                                commit_id = m.group('commit_id'),
                                repository = self.repository,
                                branch = self
                            ).first()
                            if last_existing_commit:
                                #found the commit
                                break

                    if last_existing_commit:
                        squashed_commits = Commit.objects.filter(repository=self.repository,branch=self,id__gt=last_existing_commit.id,id__lt=commit.id)
                    else:
                        squashed_commits = Commit.objects.filter(repository=self.repository,branch=self,id__lt=commit.id)

                    if squashed_commits.exists():
                        #some commits are squashed
                        logger.info("Some commits of {} are squashed".format(self))
                        first_squashed_commit = None
                        for obj in squashed_commits:
                            if first_squashed_commit is None:
                                first_squashed_commit = obj
                            obj.squash()

                        self.scaned = False
                        self.base_commit = None
                        self.last_scaned_commit = last_existing_commit
                        if last_existing_commit is None:
                            self.last_scaned = None
                        
                        self.save(update_fields=["scaned","last_scaned_commit","last_scaned"])
                        if self.repository.scaned:
                            self.repository.scaned = False
                            self.repository.save(update_fields=["scaned"])

            else:
                last_existing_commit = commit
        update_fields = []

        if not self.is_master_branch and self.base_commit is None:
            next_base_commit_qs = Commit.objects.raw("""
            SELECT * 
            FROM github_commit a 
            WHERE a.repository_id = {0} and a.branch_id = {2} and not exists(select 1 from github_commit b where b.repository_id={0} and b.branch_id={1} and a.commit_id = b.commit_id)
            ORDER BY a.id
            LIMIT 1
            """.format(self.repository.id,self.id,self.master_branch.id))
            next_base_commit = next_base_commit_qs[0] if next_base_commit_qs else None

            if not next_base_commit:
                base_commit = Commit.objects.filter(repository=self.repository,branch=self.master_branch).order_by("-id").first()
            else:
                base_commit = next_base_commit.previous_commit()

            if base_commit:
                self.base_commit = Commit.objects.get(repository=self.repository,branch=self,commit_id=base_commit.commit_id)
            else:
                self.base_commit = None
            update_fields.append("base_commit")

        if self.is_master_branch and self.base_commit is None:
            self.base_commit = Commit.objects.filter(repository=self.repository,branch=self).order_by("id").first()
            update_fields.append("base_commit")

        if self.last_commit != commit:
            self.last_commit = commit
            update_fields.append("last_commit")


        if self.scaned:
            if self.last_scaned_commit != self.last_commit:
                self.scaned = False
                update_fields.append("scaned")
                if self.repository.scaned:
                    self.repository.scaned = False
                    self.repository.save(update_fields=["scaned"])
        if update_fields:
            self.save(update_fields=update_fields)

    def scan(self,counter=0):
        if not self.repository.account.active or not self.repository.active or not self.active:
            #not active, no need sync
            return

        if not self.synced:
            self.sync()

        if self.scaned:
            #already scaned
            return 

        if not self.is_master_branch and not self.master_branch.scaned:
            #master branch is not scaned
            raise Exception("Before scan the branch({1}) of the repository({0}), please scan the master branch first.".format(self.repository,self.name))

        leak_rules = LeakRule.objects.filter(active=True).order_by("id")
        scan_statuses = list(ScanStatus.objects.filter(repository=self.repository,branch=self).order_by("start_commit__id"))
        if self.last_scaned_commit:
            scan_statuses = list(ScanStatus.objects.filter(repository=self.repository,branch=self).order_by("start_commit__id"))
        else:
            scan_statuses = []
            update_fields = []
            if not self.is_master_branch:
                if self.base_commit:
                    self.last_scaned_commit = self.base_commit
                    self.last_scaned = timezone.now()
                    update_fields.append("last_scaned_commit")
                    update_fields.append("last_scaned")
                    #generate the scan status
                    for rule in leak_rules:
                        scan_status,created = ScanStatus.objects.get_or_create(
                            rule=rule,
                            repository=self.repository,
                            branch=self,
                            defaults = {
                                "start_commit":self.first_commit,
                                "end_commit":self.base_commit,
                                "start_scan_time":timezone.now(),
                                "end_scan_time":timezone.now()
                            }
                        )
                        scan_statuses.append(scan_status)
    
                if self.base_commit == self.last_commit:
                    self.scaned = True
                    update_fields.append("scaned")

                self.save(update_fields=update_fields)
                #update repository's scaned to True if all branches have been scaned
                if self.scaned:
                    if not Branch.objects.filter(repository=self.repository,scaned=False).exists():
                        self.repository.scaned = True
                        self.repository.save(update_fields=["scaned"])

        commits = Commit.objects.filter(repository=self.repository,branch=self)
        if self.last_scaned_commit:
            commits = commits.filter(id__gt=self.last_scaned_commit.id)
        commits = commits.order_by("id")

        previous_commit = self.last_scaned_commit
        count = 0
        for commit in commits[:counter] if counter > 0 else commits:
            logger.debug("Scan commit {}({})".format(commit.id,commit.commit_id))
            if previous_commit:
                self._scan_commit(commit,previous_commit,scan_statuses=scan_statuses,leak_rules = leak_rules)
            else:
                #perfrom the history scan from start
                self._scan_initial_commit(commit,scan_statuses=scan_statuses,leak_rules=leak_rules)
            previous_commit = commit
            count += 1
            if count >= 100:
                self.repository.last_process_start = timezone.now()
                self.repository.save(update_fields = ["last_process_start"])
                count = 0


        if self.last_commit == previous_commit:
            self.scaned = True
            self.save(update_fields=["scaned"])
            if not Branch.objects.filter(repository=self.repository,scaned=False,active=True).exists():
                self.repository.scaned = True
                self.repository.save(update_fields=["scaned"])
            
    def _post_scan_commit(self,scaned_rules,commit,previous_commit,scan_start_time,scan_statuses=None):
        for rule in scaned_rules:
            if previous_commit :
                #not the initial commit
                if scan_statuses is not None:
                    try:
                        scan_status = next(s for s in scan_statuses if s.rule.id == rule.id and s.end_commit.id == previous_commit.id)
                    except:
                        raise ObjectDoesNotExist("ScanStatus(repository={}, branch={}, rule={},end_commit={})".format(
                            commit.repository,
                            commit.branch,
                            rule,
                            previous_commit)
                        )
                else:
                    try:
                        scan_status = ScanSatus.objects.filter(repository=commit.repository,branch=commit.branch,rule=rule,end_commit=previous_commit).get()
                    except ObjectDoesNotExist:
                        raise ObjectDoesNotExist("ScanStatus(repository={}, branch={}, rule={},end_commit={})".format(
                            commit.repository,
                            commit.branch,
                            rule,
                            previous_commit)
                        )
                scan_status.end_commit = commit
                scan_status.end_scan_time = timezone.now()
                try:
                    scan_status.save(update_fields=["end_commit","end_scan_time"])
                except:
                    if not ScanStatus.objects.filter(pk=scan_status.pk).exists():
                        #rule has been changed.
                        raise Exception("Rule({}) has been changed".format(rule))
            else:
                #initial commit
                scan_status = ScanStatus(
                    rule=rule,
                    repository=commit.repository,
                    branch=commit.branch,
                    start_commit=commit,
                    end_commit=commit,
                    start_scan_time=scan_start_time,
                    end_scan_time=timezone.now())
                scan_status.save()
    
                if scan_statuses is not None:
                    scan_statuses.append(scan_status)

        now = timezone.now()
        logger.debug("{} last scaned commit = {}".format(self.name,commit))
        if self.last_scaned_commit:
            if not Branch.objects.filter(pk=self.pk,last_scaned_commit=self.last_scaned_commit).update(last_scaned_commit=commit,last_scaned=now):
                raise Exception("The history scan status of the branch({}) has been changed".format(self))
        else:
            if not Branch.objects.filter(pk=self.pk,last_scaned_commit__isnull=True).update(last_scaned_commit=commit,last_scaned=now):
                raise Exception("The history scan status of the branch({}) has been changed".format(self))

        self.last_scaned_commit = commit
        self.last_scaned = now

    _excluded_files = None
    def _is_excluded(self,file_name,repository_file_path,file_path):
        if not self._excluded_files:
            self._excluded_files = ExcludedFile.objects.filter(active=True)

        for excluded_file in self._excluded_files:
            if excluded_file.check_repository(self.repository) and excluded_file.checking(file_path):
                return True
        return False


    def _scan_initial_commit(self,initial_commit=None,scan_statuses = None,leak_rules = None,previous_commit=None,already_checkout=False):
        """
        initial commit can be the first commit or a commit without parent commit
        scan_statuses if provided should be scan status list belong to the branch
        """
        initial_commit = initial_commit or self.first_commit;
        if not initial_commit:
            return
        if not already_checkout:
            #checkout the initial commit
            cmd = "cd {} && git stash -u && git stash clear && git checkout {} ".format(self.repository.local_repo_folder,initial_commit.commit_id)
            logger.debug("run command '{}'".format(cmd))
            subprocess.check_call(cmd,shell=True)
        #find all files
        folders = [self.repository.local_repo_folder]

        scan_statuses = scan_statuses or list(ScanStatus.objects.filter(repository=self.repository,branch=self).order_by("start_commit__id"))

        leak_rules = leak_rules or LeakRule.objects.filter(active=True).order_by("id")

        required_rules = []
        for rule in leak_rules:
            if rule.is_scaned(initial_commit,scan_statuses):
                #already scaned, ignore
                continue
            required_rules.append(rule)

        if not required_rules:
            #all rules are scaned
            return
            
        logger.debug("Required scan rules '{}' for commit({})".format(required_rules,initial_commit))

        scan_start_time = timezone.now()
        while folders:
            folder = folders.pop(0)
            logger.debug("scan folder '{}'".format(folder))
            files = os.listdir(folder)
            for file_name in files:
                if file_name == ".git":
                    #git reserved folder
                    continue
                file_path = os.path.join(folder,file_name)
                if os.path.isdir(file_path):
                    folders.append(file_path)
                    continue
                if self._is_excluded(file_name,self.repository.repository_file_path(file_path),file_path):
                    #excluded
                    logger.debug("File({}) is excluded.".format(file_path))
                    continue
                if file_type(file_path) == TEXT_FILE:
                    scan_content = FileScanContent(initial_commit,None,file_name,file_path)
                else:
                    scan_content = BinaryFileScanContent(initial_commit,None,file_name,file_path)

                for rule in required_rules:
                    rule.scan(scan_content)

        self._post_scan_commit(required_rules,initial_commit,previous_commit,scan_start_time,scan_statuses=scan_statuses)

    line_number_separator = re.compile("@+")
    file_prefix = "diff --git ".encode()
    line_number_prefix = "@@ ".encode()
    deleted_file_prefix = "deleted file mode".encode()
    new_file_prefix = "new file mode".encode()
    binary_file_prefix = "Binary files ".encode()
    add_line_prefix = "+".encode()
    remove_line_prefix = "-".encode()
    end_file = "".encode()
    def _scan_commit(self,commit,previous_commit,scan_statuses = None,leak_rules = None):
        scan_statuses = scan_statuses or list(ScanStatus.objects.filter(repository=self.repository,branch=self).order_by("start_commit__id"))

        leak_rules = leak_rules or LeakRule.objects.filter(active=True).order_by("id")

        required_rules = []
        required_useless_file_rules = None
        content_match_required = False
        for rule in leak_rules:
            if rule.is_scaned(commit,scan_statuses):
                #already scaned, ignore
                continue
            if rule.content_match:
                content_match_required = True
            if rule.category == rule.USELESS_FILE:
                if required_useless_file_rules:
                    required_useless_file_rules.append(rule)
                else:
                    required_useless_file_rules = [rule]
            required_rules.append(rule)

        if not required_rules:
            #all rules are scaned
            return
            
        logger.debug("Required scan rules '{}' for commit({})".format(required_rules,commit))
        scan_start_time = timezone.now()
        if commit.is_merge_commit:
            #is a merge commit; all changes are scaned in the previous commit,ignore this commit
            self._post_scan_commit(required_rules,commit,previous_commit,scan_start_time,scan_statuses=scan_statuses)
            return


        #cmd1 = "cd {} && git stash -u && git stash clear && git checkout {} && git checkout {}".format(self.repository.local_repo_folder,self.name,commit.commit_id)
        cmd1 = "cd {} && git stash -u && git stash clear && git checkout {}".format(self.repository.local_repo_folder,commit.commit_id)
        logger.debug("run command '{}'".format(cmd1))
        subprocess.check_call(cmd1,shell=True)

        #checkout the initial commit
        with tempfile.NamedTemporaryFile(delete=False) as f:
            diff_file = f.name
            err_file = "{}.err".format(diff_file)
        #get the difference between the commit and previous commit
        cmd2 = "cd {0} && git diff --no-color {1}~ {1} > {2} 2>{3}".format(self.repository.local_repo_folder,commit.commit_id,diff_file,err_file)
        logger.debug("run command '{}'".format(cmd2))
        try:
            try:
                subprocess.check_call(cmd2,shell=True)
            except Exception as ex:
                with open(err_file,'r') as ef:
                    msg = ef.read()
                if "'{}~': unknown revision or path not in the working tree.".format(commit.commit_id) in msg:
                    #this commit has no parents.
                    self._scan_initial_commit(initial_commit=commit,previous_commit=previous_commit,scan_statuses = scan_statuses,leak_rules = leak_rules,already_checkout=True)
                    return
                else:
                    raise

           
            scan_content = None
            files = None
            line_numbers = None #[(src base line number,lines),(target base line number,lines)]
            src_file_differences = None
            target_file_differences = None
            added_lines = 0
            removed_lines = 0
            scan_content = None
            file_change_mode = None

            f = open(diff_file,'rb')
            next_line = f.readline()
            while next_line != self.end_file:
                line = next_line
                next_line = None
                try:
                    if line[0:len(self.file_prefix)] == self.file_prefix:
                        #if files and files[1][2].endswith("pbs_prod_07Apr2016.pgdump") :
                        #    import ipdb;ipdb.set_trace()
                        if scan_content:
                            #process the previous file first.
                            if file_change_mode == "update"  and line_numbers and added_lines > 0:
                                scan_content.add_chunk(
                                        line_numbers[0][0],
                                        src_file_differences if src_file_differences else "",
                                        line_numbers[1][0],
                                        target_file_differences if target_file_differences else "",
                                        "update" if removed_lines > 0 else "add")
    
                            if isinstance(scan_content,DeletedFileScanContent):
                                #file was deleted
                                #remove useless file leaks and useless file excluded leaks 
                                for r in required_useless_file_rules:
                                    if r.rule_re.search(scan_content.file_name):
                                        #is a useless file,but was removed from repository, try to delete the leaks and excluded leaks
                                        Leak.objects.filter(repository=scan_content.commit.repository,branch=scan_content.commit.branch,rule__category=LeakRule.USELESS_FILE,file=scan_content.repository_file_path).delete()
                                        ExcludedLeak.objects.filter(repository=scan_content.commit.repository,branch=scan_content.commit.branch,rule__category=LeakRule.USELESS_FILE,file=scan_content.repository_file_path).delete()
                                        break
                            else:
                                for rule in required_rules:
                                    rule.scan(scan_content)

                        #start a new file
                        line_numbers = None #[(src base line number,lines),(target base line number,lines)]
                        src_file_differences = None
                        target_file_differences = None
                        added_lines = 0
                        removed_lines = 0
                        scan_content = None
                        file_change_mode = None
                        #get the source and target file name 
                        #data structure is ((src file name,src file repository file path,src file path),(target file name,target file repository path,target file path))
                        file_lines = line[len("diff --git "):].decode().strip()
                        files = [ file_name for file_name in file_lines.split() if file_name]
                        for s in ["\"","'"]:
                            if files[0][0] == s:
                                files[0] = files[0].strip(s)
                                break
                        for s in ["\"","'"]:
                            if files[1][0] == s:
                                files[1] = files[1].strip(s)
                                break
    
                        if files[0][0:2] != 'a/' and files[1][0:2] != 'b/':
                            raise Exception("Parse git diff first line({}) failed.{}.cmd={} && {}".format(files,file_lines,cmd1,cmd2))
                        files[0] = (os.path.split(files[0])[1],files[0][1:],os.path.join(commit.repository.local_repo_folder,files[0][2:]))
                        files[1] = (os.path.split(files[1])[1],files[1][1:],os.path.join(commit.repository.local_repo_folder,files[1][2:]))
                        if self._is_excluded(*files[1]):
                            #file is excluded
                            file_change_mode = "excluded"
                            scan_content = None
                        else:
                            if os.path.exists(files[1][2]):
                                if file_type(files[1][2]) != TEXT_FILE:
                                    file_change_mode = "binary"
                                    scan_content = BinaryFileScanContent(commit,previous_commit,files[1][0],files[1][2])
                            else:
                                file_change_mode = "delete"
                                scan_content = DeletedFileScanContent(commit,previous_commit,files[1][0],files[1][2]) if required_useless_file_rules else None
                    elif files:
                        if file_change_mode == "excluded":
                            #excluded, no need to scan
                            continue
                        elif file_change_mode == "binary":
                            #a binary file, no need to scan
                            continue
                        elif file_change_mode == "create":
                            #a file,get the content from file system. 
                            continue
                        elif file_change_mode == "delete":
                            #remote a file, no need to scan
                            continue
                        elif line[0:len(self.new_file_prefix)] == self.new_file_prefix:
                            file_change_mode = "create"
                            scan_content = FileScanContent(commit,previous_commit,files[1][0],files[1][2])
                        elif line[0:len(self.deleted_file_prefix)] == self.deleted_file_prefix:
                            file_change_mode = "delete"
                            if scan_content is None and required_useless_file_rules:
                                scan_content = DeletedFileScanContent(commit,previous_commit,files[1][0],files[1][2])
                        elif line[0:len(self.binary_file_prefix)] == self.binary_file_prefix:
                            file_change_mode = "binary"
                            scan_content = BinaryFileScanContent(commit,previous_commit,files[1][0],files[1][2])
                        elif not content_match_required:
                            #content match is not required
                            continue
                        elif line[0:len(self.line_number_prefix)] == self.line_number_prefix:
                            #start a file content difference
                            file_change_mode = "update"
                            if scan_content is None :
                                scan_content = FileDiffScanContent(commit,previous_commit,files[1][0],files[1][2])
                            if line_numbers and added_lines > 0:
                                scan_content.add_chunk(
                                        line_numbers[0][0],
                                        src_file_differences if src_file_differences else "",
                                        line_numbers[1][0],
                                        target_file_differences if target_file_differences else "",
                                        "update" if removed_lines > 0 else "add")
    
                            difference_line = line.decode().strip("@")
                            added_lines = 0
                            removed_lines = 0
                            line_numbers = None
                            src_file_differences = ""
                            target_file_differences = ""
                            
                            difference_line = line.decode().strip().strip("@")
                            line_number_lines = [ l.strip() for l in self.line_number_separator.split(difference_line,1) if l.strip()]
                            if len(line_number_lines) == 2:
                                #a line of file content was found after the line number
                                next_line = line_number_lines[1].encode()
                            line_numbers = line_number_lines[0].split()
                            if len(line_numbers) != 2 :
                                raise Exception("Parse git diff line number line({}) failed.{}.cmd={} && {}".format(line_numberes,difference_line,cmd1,cmd2))
    
                            line_numbers = [[l.strip() for l in line_numbers[0].split(",")],[l.strip() for l in line_numbers[1].split(",")]]
                            if line_numbers[0][0][0] != '-' or line_numbers[1][0][0] != '+':
                                raise Exception("Parse git diff line number line({}) failed.{}.cmd={} && {}".format(line_numbers,difference_line,cmd1,cmd2))
                            try:
                                line_numbers = [
                                    (int(line_numbers[0][0][1:]),int(line_numbers[0][1] if len(line_numbers[0]) == 2 else 0 )),
                                    (int(line_numbers[1][0][1:]),int(line_numbers[1][1] if len(line_numbers[1]) == 2 else 0 ))
                                ]
                            except:
                                raise Exception("Parse git diff line number line({}) failed.{}.cmd={} && {}".format(line_numbers,difference_line,cmd1,cmd2))
                        elif line_numbers:
                            #file diff content
                            if line[0:len(self.add_line_prefix)] == self.add_line_prefix:
                                try:
                                    difference_line = line[len(self.add_line_prefix):].decode()
                                except:
                                    #decode failed,ignore
                                    logger.warning("Decode line failed,line={},file={},cmd={} & {}".format(line,files[1][2] if files else "",cmd1,cmd2))
                                    difference_line = ""
                                if difference_line.strip():
                                    #add a non empty line
                                    added_lines += 1
                                target_file_differences += difference_line
                            elif line[0:len(self.remove_line_prefix)] == self.remove_line_prefix:
                                removed_lines += 1
                                try:
                                    difference_line = line[len(self.remove_line_prefix):].decode()
                                except:
                                    #decode failed,ignore
                                    logger.warning("Decode line failed,line={},file={},cmd={} & {}".format(line,files[1][2] if files else "",cmd1,cmd2))
                                    difference_line = ""
                                src_file_differences += difference_line
                            else:
                                try:
                                    difference_line = line.decode()
                                except:
                                    #decode failed,ignore
                                    logger.warning("Decode line failed,line={},file={},cmd={} & {}".format(line,files[1][2] if files else "",cmd1,cmd2))
                                    difference_line = ""
                                src_file_differences += difference_line
                                target_file_differences += difference_line
                        else:
                            #lines between file head and first file difference,ignore
                            pass
                except Exception as ex:
                    raise Exception("{},line={},file={},cmd={} & {}".format(str(ex),line,files[1][2] if files else "",cmd1,cmd2))
                finally:
                    if next_line is None:
                        next_line = f.readline()
            #process the last file
            if scan_content:
                #process the previous file first.
                if file_change_mode == "update"  and line_numbers and added_lines > 0:
                    scan_content.add_chunk(
                            line_numbers[0][0],
                            src_file_differences if src_file_differences else "",
                            line_numbers[1][0],
                            target_file_differences if target_file_differences else "",
                            "update" if removed_lines > 0 else "add")

                if isinstance(scan_content,DeletedFileScanContent):
                    #file was deleted
                    #remove useless file leaks and useless file excluded leaks 
                    for r in required_useless_file_rules:
                        if r.rule_re.search(scan_content.file_name):
                            #is a useless file,but was removed from repository, try to delete the leaks and excluded leaks
                            Leak.objects.filter(repository=scan_content.commit.repository,branch=scan_content.commit.branch,rule__category=LeakRule.USELESS_FILE,file=scan_content.repository_file_path).delete()
                            ExcludedLeak.objects.filter(repository=scan_content.commit.repository,branch=scan_content.commit.branch,rule__category=LeakRule.USELESS_FILE,file=scan_content.repository_file_path).delete()
                            break
                else:
                    for rule in required_rules:
                        rule.scan(scan_content)

        finally:
            try:
                if f:
                    f.close()
            except:
                pass
            try:
               os.remove(diff_file)
            except:
                pass

            try:
               os.remove(err_file)
            except:
                pass

        self._post_scan_commit(required_rules,commit,previous_commit,scan_start_time,scan_statuses=scan_statuses)


    @property
    def first_commit(self):
        return Commit.objects.filter(repository=self.repository,branch=self).order_by("id").first()


    def __str__(self):
        return "{}:{}".format(self.repository,self.name)

    class Meta:
        unique_together = ('repository', 'name')
        ordering = ('repository','name')

class Commit(models.Model):
    commit_id = models.CharField(max_length=256,editable=False)
    repository = models.ForeignKey(Repository, on_delete=models.PROTECT,null=False,related_name="+")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT,null=False,editable=False,related_name="+")
    merge = models.CharField(max_length=256,null=True,editable=False)
    author = models.CharField(max_length=128,editable=False)
    comments = models.TextField(editable=False)
    committed = models.DateTimeField(null=False,editable=False)


    @property
    def is_merge_commit(self):
        return True if self.merge else False

    def get_file(self,repository_file_path):
        #checkout the right branch and right commit
        cmd = "cd {} && git checkout {} && git checkout {}".format(self.repository.local_repo_folder,self.branch.name,self.commit_id)
        logger.debug("run command '{}'".format(cmd))
        subprocess.check_call(cmd,shell=True)
        file_path = self.repository.file_path(repository_file_path)
        ftype = file_type(file_path) 
        return (file_path,ftype)


    def read_file(self,repository_file_path):
        #checkout the right branch and right commit
        file_path,ftype = self.get_file(repository_file_path)
        with open(file_path,'r' if ftype == TEXT_FILE else 'rb') as f:
            return f.read()


    def squash(self):
        #delete all leaks related to this commit
        Leak.objects.filter(repository=self.repository,branch=self,commit=self.id).delete()

        previous_commit = self.previous_commit()
        #process the scanstatus whose start_commit is the squashed commit
        scan_statuses = ScanStatus.objects.filter(repository=self.repository,branch=self.branch,start_commit__gte = self ,end_commit__lte=self)
        for scan_status in scan_statuses:
            if scan_status.start_commit == self:
                scan_status.delete()
            elif not previous_commit:
                scan_status.delete()
            else:
                scan_status.end_commit = previous_commit
                scan_status.save(update_fields=["end_commit"])

        self.delete()
                

    def next_commit(self):
        return Commit.objects.filter(repository=self.repository,branch=self.branch,id__gt=self.id).order_by("id").first()

    def previous_commit(self):
        return Commit.objects.filter(repository=self.repository,branch=self.branch,id__lt=self.id).order_by("-id").first()

    def __str__(self):
        return "{} ({})".format(self.commit_id,self.committed.strftime("%Y-%m-%d %H:%M:%S"))

    class Meta:
        unique_together = ('repository','branch', 'commit_id')
        ordering = ('repository','branch','committed')

class LeakRule(models.Model):
    _rule_re = None
    _excluded_values = None

    DATABASE_URL = 1
    ENV_FILE = 2
    CREDENTIAL = 3
    FILE = 4
    USELESS_FILE = 5
    CATEGORY_CHOICES = (
        (DATABASE_URL,"Database URL"),
        (ENV_FILE,"Env File"),
        (CREDENTIAL,"Credential"),
        (FILE,"File"),
        (USELESS_FILE,"Useless File"),
    )
    WARNING = 1
    LOW_RISK = 2
    MEDIUM_RISK = 3
    HIGH_RISK = 4
    RISK_CHOICES = (
        (WARNING,"Warning"),
        (LOW_RISK,"Low Risk"),
        (MEDIUM_RISK,"Medium Risk"),
        (HIGH_RISK,"High Risk"),
    )
    name = models.CharField(max_length=64)
    regex = models.CharField(max_length=256)
    content_match = models.BooleanField(default=True)
    risk_level = models.SmallIntegerField(choices=RISK_CHOICES)
    comments = models.CharField(max_length=64,editable=True,null=True,blank=True)
    category = models.SmallIntegerField(choices=CATEGORY_CHOICES)
    active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)

    def is_scaned(self,commit,scan_statuses=None):
        """
        if scan_statuses is not none, it should be the statuses belong to the commit's branch, can include scan status for all rules
        """
        if scan_statuses is not None:
            for s in scan_statuses:
                if s.rule.id == self.id and s.start_commit.id <= commit.id and s.end_commit.id >= commit.id:
                    return True
            return False
        else:
            return ScanSatus.objects.filter(repository=commit.repository,branch=commit.branch,rule=self,start_commit__id__lte=commit.id,end_commit__id__gte=commit.id).exists()

    @property
    def useless_file(self):
        return LeakRule.objects.filter(category=self.USELESS_FILE)

    @property
    def excluded_values(self):
        if not self._excluded_values:
            self._excluded_values = ExcludedValue.objects.filter(rule=self)

        return self._excluded_values

    @property
    def rule_re(self):
        if not self._rule_re:
            if self.regex.strip().startswith("re.compile"):
                #is a creating regex instance statement
                exec("self._rule_re = {}".format(self.regex))
            else:
                #is a regex string
                self._rule_re = re.compile(self.regex,re.DOTALL|re.IGNORECASE)

        return self._rule_re


    _newline_re = re.compile("\n")
    def line_number(self,string,base_line_number=1,endposition=None):
        """
        end_position included if provided
        """
        if endposition  is None:
            lines_iter = self._newline_re.finditer(string)
        else:
            lines_iter = self._newline_re.finditer(string[:endposition + 1])

        return len([i for i in lines_iter]) + base_line_number
    
    def reset_scanstatus(self):
        #reset the scan status to rescan all repository
        Branch.objects.filter(last_scaned_commit__isnull=False).update(scaned=False,last_scaned_commit=None)
        Repository.objects.filter(scaned=True).update(scaned=False)
        Repository.objects.exclude(process_status=SYNCING).update(process_status=WAITING,process_message=None,last_process_start=None,last_process_end=None)
        #remote leakrule's scanstatus
        ScanStatus.objects.filter(rule=self).delete()
        #delete leak
        Leak.objects.filter(rule=self).delete()
        #delete Excluded Leak
        ExcludedLeak.objects.filter(rule=self).delete()

    def rescan_leaks(self):
        if not self.id:
            #new rules. no existing leaks
            return

        first_excluded_leak = None

        matched_name = None
        matched_value = None
        matched_data = None

        found_excluded_value = None
        for leak in Leak.objects.filter(rule=self):
            found_excluded_value = None
            m = self.rule_re.search(leak.details)
            if m:
                #is a leak
                matched_data = m.group(0)
                try:
                    matched_value = m.group("value")
                except:
                    matched_value = m.group(0)
                
                try:
                    matched_name = m.group("name")
                except:
                    matched_name = None

                found_excluded_value = None
                for excluded_value in self.excluded_values:
                    if excluded_value.checking(leak.repository,matched_name,matched_value):
                        found_excluded_value = excluded_value
                        break

                if found_excluded_value:
                    #is excluded, remove the leak and add a excluded leak
                    excluded_leak = ExcludedLeak(
                        repository=leak.repository,
                        branch=leak.branch,
                        commit=leak.commit,
                        rule=self,
                        excluded_value = found_excluded_value,
                        file=leak.file,
                        line_number = leak.line_number,
                        name = matched_name,
                        value = matched_value,
                        details = matched_data
                    )
                    excluded_leak.save()
                    if not first_excluded_leak:
                        first_excluded_leak = excluded_leak

                    leak.delete()
                else:
                    #is still a leak
                    if matched_data == leak.details and matched_name == leak.name and matched_value == leak.value:
                        #nothing changed
                        pass
                    else:
                        #delete the leak and add a new one
                        leak.delete()
                        leak.id = None
                        leak.details = matched_data
                        leak.name = matched_name
                        leak.value = matched_value
                        leak.save()
            else:
                #not a leak, delete the leak
                leak.delete()


        found_excluded_value = None
        excluded_leak_qs =  ExcludedLeak.objects.filter(rule=self)
        if first_excluded_leak:
            excluded_leak_qs =  excluded_leak_qs.filter(id__lt=first_excluded_leak.id)
        for excluded_leak in excluded_leak_qs:
            found_excluded_value = None
            m = self.rule_re.search(excluded_leak.details)
            if m:
                #is a leak
                matched_data = m.group(0)
                try:
                    matched_value = m.group("value")
                except:
                    matched_value = m.group(0)
                
                try:
                    matched_name = m.group("name")
                except:
                    matched_name = None

                found_excluded_value = None
                for excluded_value in self.excluded_values:
                    if excluded_value.checking(excluded_leak.repository,matched_name,matched_value):
                        found_excluded_value = excluded_value
                        break

                if found_excluded_value:
                    #is  still excluded, update the excluded leak
                    if matched_data == excluded_leak.details and matched_name == excluded_leak.name and matched_value == excluded_leak.value and found_excluded_value == excluded_leak.excluded_value:
                        #nothing chaged
                        pass
                    else:
                        #delete the current instance and add a new one
                        excluded_leak.delete()
                        excluded_leak.id = None
                        excluded_leak.details = matched_data
                        excluded_leak.name = matched_name
                        excluded_leak.value = matched_value
                        excluded_leak.excluded_value = excluded_value
                        excluded_leak.save()
                else:
                    Leak(
                        repository=excluded_leak.repository,
                        branch=excluded_leak.branch,
                        commit=excluded_leak.commit,
                        rule=self,
                        file=excluded_leak.file,
                        line_number = excluded_leak.line_number,
                        name = matched_name,
                        value = matched_value,
                        details = matched_data
                    ).save()
                    excluded_leak.delete()
            else:
                #not a leak, delete the leak
                excluded_leak.delete()

    def scan(self,scan_content):
        if self.content_match:
            #this rule is to scan the content
            content_chunks = scan_content.chunks()
            if not content_chunks:
                return
        else:
            #this rule is to scan the file name
            content_chunks = [((0,None),(1,scan_content.file_name),"add")]

        #remove the scan result from Leak table if have
        Leak.objects.filter(repository=scan_content.commit.repository,branch=scan_content.commit.branch,commit=scan_content.commit,rule=self,file=scan_content.repository_file_path).delete()
        ExcludedLeak.objects.filter(repository=scan_content.commit.repository,branch=scan_content.commit.branch,commit=scan_content.commit,rule=self,file=scan_content.repository_file_path).delete()

        matched_name = None
        matched_value = None
        matched_data = None
        src_chunk_pos = 0
        for src_chunk,target_chunk,mode in content_chunks:
            for m in self.rule_re.finditer(target_chunk[1]):
                matched_data = m.group(0)
                try:
                    matched_value = m.group("value")
                except:
                    matched_value = m.group(0)
                
                try:
                    matched_name = m.group("name")
                except:
                    matched_name = None

                if mode == "update":
                    index = src_chunk[1].find(matched_data,src_chunk_pos)
                    if index >= 0:
                        #the matched_value is already in src chunk, not a new leak
                        src_chunk_pos = index + len(matched_data)
                        continue

                logger.debug("Found a leak.rule={}, value={}, name={}, details={}".format(self,matched_value,matched_name,matched_data))
                line_number = self.line_number(target_chunk[1],target_chunk[0],m.start(0))
                try:

                    found_excluded_value = None
                    for excluded_value in self.excluded_values:
                        if excluded_value.checking(scan_content.commit.repository,matched_name,matched_value):
                            found_excluded_value = excluded_value
                            break
                    if found_excluded_value:
                        #excluded
                        ExcludedLeak(
                            repository=scan_content.commit.repository,
                            branch=scan_content.commit.branch,
                            commit=scan_content.commit,
                            rule=self,
                            excluded_value = found_excluded_value,
                            file=scan_content.repository_file_path,
                            line_number = line_number,
                            name = matched_name,
                            value = matched_value,
                          details = matched_data
                        ).save()
                    else:
                        Leak(
                            repository=scan_content.commit.repository,
                            branch=scan_content.commit.branch,
                            commit=scan_content.commit,
                            rule=self,
                            file=scan_content.repository_file_path,
                            line_number = line_number,
                            name = matched_name,
                            value = matched_value,
                          details = matched_data
                        ).save()
                except Exception as ex:
                    raise ex.__class__("{},file={} ,name={}, value={} ,details={}".format(str(ex),scan_content.commit.repository.repository_file_path(scan_content.file_path),matched_name,matched_value,matched_data))

    def __str__(self):
        return self.name

    class Meta:
        ordering = ('name',)


class CodeMixin(models.Model):
    _check_method = None
    _rule_re = None
    _method_name="check"
    code = models.TextField(null=False)

    @property
    def rule_re(self):
        if not self._rule_re:
            if self.code.strip().startswith("re.compile"):
                #is a creating regex instance statement
                exec("self._rule_re = {}".format(self.code))
            else:
                code = [l for l in self.code.split("\n") if l.strip()]
                if len(code) == 1:
                    #is a regex string
                    self._rule_re = re.compile(code[0],re.DOTALL|re.IGNORECASE)
                else:
                    raise Exception("Not a valid regex")

        return self._rule_re

    def rule_re_checkmethod(self):
        return lambda value:True if self.rule_re.search(value) else False

    def checking(self,*args):
        if not self._check_method:
            if not self.code.strip():
                self._check_method = lambda value:False
            else:
                #it is regex string
                try:
                    if self.rule_re:
                        self._check_method = self.rule_re_checkmethod()
                except:
                    module_name = "{}_{}".format(self.__class__.__name__,self.id)
                    m = imp.new_module(module_name)
                    exec(self.code,m.__dict__)
                    if not hasattr(m,self._method_name):
                        #no event processing method
                        raise Exception("'is_excluded' method is not found in ExcludedFile({})".format(self.name))
                    self._check_method = getattr(m,self._method_name)

        return self._check_method(*args)

    class Meta:
        abstract=True

class ExcludedValue(CodeMixin,models.Model):
    _method_name="is_excluded"
    rule = models.ForeignKey(LeakRule, on_delete=models.CASCADE,null=False,related_name="+")
    repositories = models.CharField(max_length=512,null=True,blank=True)
    added = models.DateTimeField(auto_now_add=True)

    def rule_re_checkmethod(self):
        return lambda name,value:True if self.rule_re.search(value) else False

    def checking(self,repository,name,value):
        if self.repositories:
            repository_re = re.compile("(^|\,)\s*(?P<name>{})\s*(\,|$)".format(repository.name),re.IGNORECASE)
            if not repository_re.search(self.repositories):
                #repository not in repositories, not excluded
                return False

        return super().checking(name,value)

class ExcludedFile(CodeMixin,models.Model):
    _method_name="is_excluded"
    name = models.CharField(max_length=64)
    repositories = models.CharField(max_length=512,null=True,blank=True)
    comments = models.CharField(max_length=64,editable=True,null=True,blank=True)
    active = models.BooleanField(default=True)
    added = models.DateTimeField(auto_now_add=True)

    def check_repository(self,repository):
        """
        Return True if this instance is suitable for the repository;otherwise return False
        """
        if self.repositories:
            repository_re = re.compile("(^|\,)\s*(?P<name>{})\s*(\,|$)".format(repository.name),re.IGNORECASE)
            return True if repository_re.search(self.repositories) else False
        else:
            #suitable for all repositories
            return True



class Leak(models.Model):
    repository = models.ForeignKey(Repository, on_delete=models.PROTECT,null=False,editable=False,related_name="leaks")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT,null=False,editable=False,related_name="+")
    commit = models.ForeignKey(Commit, on_delete=models.PROTECT,null=False,editable=False,related_name="+")
    rule = models.ForeignKey(LeakRule, on_delete=models.CASCADE,null=False,editable=False,related_name="+")
    file = models.CharField(max_length=512,editable=False,null=False)
    line_number = models.IntegerField(null=True,editable=False)
    name = models.CharField(max_length=256,editable=False,null=True)
    value = models.CharField(max_length=1024,editable=False,null=False)
    details = models.TextField(editable=False,null=False)
    found = models.DateTimeField(auto_now_add=True)

class ExcludedLeak(models.Model):
    repository = models.ForeignKey(Repository, on_delete=models.PROTECT,null=False,editable=False,related_name="+")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT,null=False,editable=False,related_name="+")
    commit = models.ForeignKey(Commit, on_delete=models.PROTECT,null=False,editable=False,related_name="+")
    rule = models.ForeignKey(LeakRule, on_delete=models.CASCADE,null=False,editable=False,related_name="+")
    excluded_value = models.ForeignKey(ExcludedValue, on_delete=models.CASCADE,null=False,editable=False,related_name="+")
    file = models.CharField(max_length=512,editable=False,null=False)
    line_number = models.IntegerField(null=True,editable=False)
    name = models.CharField(max_length=256,editable=False,null=True)
    value = models.CharField(max_length=1024,editable=False,null=False)
    details = models.TextField(editable=False,null=False)
    found = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["rule","excluded_value"])]

class ScanStatus(models.Model):
    rule = models.ForeignKey(LeakRule, on_delete=models.CASCADE,null=False,editable=False,related_name="+")
    repository = models.ForeignKey(Repository, on_delete=models.PROTECT,null=False,editable=False,related_name="+")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT,null=False,editable=False,related_name="+")
    start_commit = models.ForeignKey(Commit, on_delete=models.PROTECT,null=False,editable=False,related_name="+")
    end_commit = models.ForeignKey(Commit, on_delete=models.PROTECT,null=True,editable=False,related_name="+")
    start_scan_time = models.DateTimeField(null=False,editable=False)
    end_scan_time = models.DateTimeField(null=False,editable=False)

    class Meta:
        unique_together = ('rule','repository','branch','start_commit')

class ExcludedFileListener(object):
    @staticmethod
    @receiver(pre_save, sender=ExcludedFile)
    def add_excludedfile(sender,instance,**kwargs):
        #scan the excluded leaks and excluded leaks,
        if instance.pk:
            existing_instance = ExcludedFile.objects.get(id = instance.id)
            if existing_instance.code == instance.code and existing_instance.repositories == instance.repositories and existing_instance.active == instance.active:
                return
            #return

        if not instance.active:
            return

        leak_qs = Leak.objects.all().order_by("id")
        excluded_leak_qs = ExcludedLeak.objects.all().order_by("id")
        if instance.repositories:
            repos = [r.strip() for r in instance.repositories.split(",") if r.strip()]
            repos_re = r"^({})$".format("|".join(repos))
            leak_qs = leak_qs.filter(repository__name__iregex=repos_re)
            excluded_leak_qs = excluded_leak_qs.filter(repository__name__iregex=repos_re)

        for leak_set in (leak_qs,excluded_leak_qs):
            for leak in leak_set:
                if instance.check_repository(leak.repository) and instance.checking(leak.file):
                    #excluded
                    leak.delete()

class LeakRuleListener(object):
    @staticmethod
    #@receiver(pre_save, sender=LeakRule)
    def update_leak_rule(sender,instance,**kwargs):
        #reset branch scan status
        existing_instance = LeakRule.objects.get(id=instance.id) if instance.id else None
        if not instance.pk or existing_instance.regex != instance.regex:
            Branch.objects.filter(last_scaned_commit__isnull=False).update(scaned=False,last_scaned_commit=None)
            Repository.objects.filter(scaned=True).update(scaned=False)
            #remote leakrule's scanstatus
            if instance.pk:
                ScanStatus.objects.filter(rule=instance).delete()
                #delete leak
                Leak.objects.filter(rule=instance).delete()
                #delete Excluded Leak
                ExcludedLeak.objects.filter(rule=instance).delete

    """
    @staticmethod
    @receiver(pre_save, sender=LeakRule)
    def delete_leak_rule(sender,instance,**kwargs):
        LeakRuleListener._reset_rule_scan_status(instance,True)
    """

    @staticmethod
    @receiver(pre_save, sender=ExcludedValue)
    def update_excluded_value(sender,instance,**kwargs):
        if instance.pk:
            #update
            existing_instance = ExcludedValue.objects.get(id=instance.id)
            if existing_instance.code != instance.code:
                #update
                #scan the leaks to find new excluded leaks, but not save to db
                first_excluded_leak = None
                for leak in Leak.objects.filter(rule = instance.rule):
                    if instance.checking(leak.repository,leak.name,leak.value):
                        #excluded
                        excluded_leak = ExcludedLeak(
                            repository=leak.repository,
                            branch=leak.branch,
                            commit=leak.commit,
                            rule=leak.rule,
                            excluded_value = instance,
                            file=leak.file,
                            line_number = leak.line_number,
                            name = leak.name,
                            value = leak.value,
                            details = leak.details
                        )
                        excluded_leak.save()
                        if not first_excluded_leak:
                            first_excluded_leak = excluded_leak
                        leak.delete()
    
                excluded_values = list(ExcludedValue.objects.filter(rule=instance.rule).exclude(id=instance.id))
                excluded_values.insert(0,instance)
                excluded_leak_qs = ExcludedLeak.objects.filter(rule=instance.rule,excluded_value=instance).order_by("id")
                if first_excluded_leak:
                    excluded_leak_qs = excluded_leak_qs.filter(id__lt = first_excluded_leak.id)

                for excluded_leak in excluded_leak_qs:
                    found_excluded_value = None

                    for excluded_value in excluded_values:
                        if excluded_value.checking(excluded_leak.repository,excluded_leak.name,excluded_leak.value):
                            #excluded by other excluded value
                            found_excluded_value = excluded_value
                            break
        
                    if found_excluded_value:
                        #excluded by other exclude value
                        excluded_leak.delete()
                        excluded_leak.id = None
                        excluded_leak.excluded_value = found_excluded_value
                        excluded_leak.save()
                    else:
                        #is a leak.
                        Leak(
                            repository=excluded_leak.repository,
                            branch=excluded_leak.branch,
                            commit=excluded_leak.commit,
                            rule=excluded_leak.rule,
                            file=excluded_leak.file,
                            line_number = excluded_leak.line_number,
                            name = excluded_leak.name,
                            value = excluded_leak.value,
                            details = excluded_leak.details
                        ).save()
                        excluded_leak.delete()

    @staticmethod
    @receiver(post_save, sender=ExcludedValue)
    def create_excluded_value(sender,instance,created,**kwargs):
        if created:
            #add an excluded value, rescan all the leaks 
            for leak in Leak.objects.filter(rule = instance.rule):
                if instance.checking(leak.repository,leak.name,leak.value):
                    #excluded
                    ExcludedLeak(
                        repository=leak.repository,
                        branch=leak.branch,
                        commit=leak.commit,
                        rule=leak.rule,
                        excluded_value = instance,
                        file=leak.file,
                        line_number = leak.line_number,
                        name = leak.name,
                        value = leak.value,
                        details = leak.details
                    ).save()
                    leak.delete()

    @staticmethod
    @receiver(pre_delete, sender=ExcludedValue)
    def delete_excluded_value(sender,instance,**kwargs):
        #scan the excluded leaks to find new leaks, and save to db
        #excluded_leak only check the excluded leak whose id is less than exccluded_leak if excluded_leak is not None
        #find all other excluded values
        excluded_values = ExcludedValue.objects.filter(rule=instance.rule).exclude(id=instance.id)
        excluded_leak_qs = ExcludedLeak.objects.filter(rule=instance.rule,excluded_value=instance).order_by("id")
        for excluded_leak in excluded_leak_qs:
            found_excluded_value = None
            for excluded_value in excluded_values:
                if excluded_value.checking(excluded_leak.repository,excluded_leak.name,excluded_leak.value):
                    #excluded by other excluded value
                    found_excluded_value = excluded_value
                    break

            if found_excluded_value:
                #excluded by other exclude value
                excluded_leak.delete()
                excluded_leak.id = None
                excluded_leak.excluded_value = found_excluded_value
                excluded_leak.save()
            else:
                #is a leak.
                Leak(
                    repository=excluded_leak.repository,
                    branch=excluded_leak.branch,
                    commit=excluded_leak.commit,
                    rule=excluded_leak.rule,
                    file=excluded_leak.file,
                    line_number = excluded_leak.line_number,
                    name = excluded_leak.name,
                    value = excluded_leak.value,
                    details = excluded_leak.details
                ).save()
                excluded_leak.delete()


