from datetime import timedelta

from django.utils import timezone

from django_q import tasks

from .models import Repository,Account

def repository_scan_task_launcher(commits = 20,scan_tasks=None):

    if not scan_tasks or scan_tasks <= 0:
        queue_size = tasks.queue_size()

        required_tasks = Repository.objects.filter(account__active=True,active=True,scaned=False).count() 
        required_tasks += Repository.objects.filter(account__active=True,active=True,scaned=True,synced=True,last_synced__lt=timezone.now() - timedelta(hours=10)).count()
        if required_tasks == 0:
            return "All repositories are synced and scaned."

        maximum_tasks = 20 - queue_size
        scan_tasks = maximum_tasks if required_tasks >= maximum_tasks else required_tasks

        if scan_tasks <= 0:
            return "Too much tasks({}) in the queue, no repository scan tasks is launched".format(queue_size)

    if commits < 0:
        commits = 20
        
    for i in range(scan_tasks):
        tasks.async_task(Repository.scan_leak,commits,group="repository_scan")

    if scan_tasks == 1:
        return "{} tasks in the queue, 1 repository scan task was launched".format(queue_size)
    else:
        return "{} tasks in the queue, {} repository scan tasks were launched".format(queue_size,scan_tasks)

def sync_account():
    #sync the actvie accounts which is not synced before
    accounts = []
    for account in Account.objects.filter(active=True,synced=False):
        account.sync()
        accounts.append(account.name)

    #sync the active accunts which is synced one days before
    for account in Account.objects.filter(active=True,synced=True,last_synced__lt=timezone.now() - timedelta(days=1)):
        account.sync(True)
        accounts.append(account.name)

    return "Github accounts({}) are synchronized".format(accounts)



