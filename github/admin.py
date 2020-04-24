import traceback

from django.contrib import admin,messages
from django.utils.safestring import mark_safe
from django.utils.encoding import filepath_to_uri

from .models import Account,Repository,Branch,Commit,LeakRule,ScanStatus,ExcludedFile,ExcludedValue,Leak,ExcludedLeak

from . import forms

# Register your models here.
@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'organization','active','synced','last_synced')
    ordering = ('-organization','name',)
    actions = ('sync',)

    def has_change_permission(self, request, obj=None):
        if obj:
            if obj.managed:
                if Repository.objects.filter(account=obj).exists():
                    return False
                if Account.objects.filter(parent=obj).exists():
                    return False
            else:
                return False
                
        return True

    def has_add_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False

    def sync(self, request, queryset):
        for account in queryset:
            try:
                account.sync(force=True)
                self.message_user(request, 'Account({}) have been synchronized.'.format(account.name))
            except Exception as ex:
                traceback.print_exc()
                self.message_user(request, 'Failed to synchronize account({}).{}'.format(account.name,str(ex)),level=messages.ERROR)

    sync.short_description = 'Sync Accounts'

class BranchInline(admin.TabularInline):
    model = Branch
    extra = 0
    readonly_fields = ("name","active","base_commit","synced","last_synced","last_commit","scaned","last_scaned","last_scaned_commit")

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ('name','account',"active","scaned", 'private','synced','last_synced','_process_status')
    readonly_fields = ("scaned", 'synced','last_synced','_process_status','process_message','last_process_start','last_process_end')
    ordering = ('account','name',)
    list_filter = ('process_status','account', 'name')
    actions = ('sync',)

    inlines = (BranchInline,)

    def _process_status(self,obj):
        return obj.get_process_status_display() if obj else ""
    _process_status.short_description = 'Histroy Scan Status'

    def has_change_permission(self, request, obj=None):
        return True

    def has_add_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False

    def sync(self, request, queryset):
        for repo in queryset:
            try:
                repo.sync(force=True)
                self.message_user(request, 'Repository({}) have been synchronized.'.format(repo))
            except Exception as ex:
                traceback.print_exc()
                self.message_user(request, 'Failed to synchronize repository({}).{}'.format(repo,str(ex)),level=messages.ERROR)

    sync.short_description = 'Sync Repository'


@admin.register(Commit)
class CommitAdmin(admin.ModelAdmin):
    list_display = ('commit_id','account_name','repository_name', 'branch_name','author','is_merge','committed')
    ordering = ('repository','branch','-id')
    list_filter = ('repository', )
    readonly_fields = ("commit_id","account_name","repository_name","branch_name","merge","author","committed","comments")
    #actions = ('sync',)


    def account_name(self,obj):
        return obj.repository.account.name if obj else ""
    account_name.short_description = 'Account'

    def repository_name(self,obj):
        return obj.repository.name if obj else ""
    repository_name.short_description = 'Repository'

    def branch_name(self,obj):
        return obj.branch.name if obj else ""
    branch_name.short_description = 'Branch'

    def is_merge(self,obj):
        return obj.is_merge_commit if obj else ""
    is_merge.short_description = 'Merge Commit?'
    is_merge.boolean = True

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

class ExcludedValueInline(admin.TabularInline):
    model = ExcludedValue
    readonly_fields = ('id',)
    extra = 1

    def has_change_permission(self, request, obj=None):
        return True

    def has_add_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return True


@admin.register(LeakRule)
class LeakRuleAdmin(admin.ModelAdmin):
    list_display = ('name','content_match','regex','category','active','created')
    ordering = ('category','name')
    list_filter = ('category', )
    actions = ('rescan_leaks','clean_scanstatus')
    form = forms.LeakRuleEditForm

    inlines = (ExcludedValueInline,)

    def has_change_permission(self, request, obj=None):
        #if obj and obj.pk:
        #    if ScanStatus.objects.filter(rule=obj).exists():
        #        return False
        #    else:
        #        return True
        return True

    def has_add_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False

    def rescan_leaks(self, request, queryset):
        for rule in queryset:
            try:
                rule.rescan_leaks()
                self.message_user(request, 'The rule({})\'s are rescaned.'.format(rule))
            except Exception as ex:
                traceback.print_exc()
                self.message_user(request, 'Failed to rescan the rule({})\'s leaks.{}'.format(rule,str(ex)),level=messages.ERROR)

    rescan_leaks.short_description = 'Rescan Leaks'

    def clean_scanstatus(self, request, queryset):
        for rule in queryset:
            try:
                rule.reset_scanstatus()
                self.message_user(request, 'The scanstaus of the rule({}) are cleaned.'.format(rule))
            except Exception as ex:
                traceback.print_exc()
                self.message_user(request, 'Failed to clean the scan status of the rule({}).{}'.format(rule,str(ex)),level=messages.ERROR)

    clean_scanstatus.short_description = 'Clean Scan Status'


@admin.register(ExcludedFile)
class ExcludedFileAdmin(admin.ModelAdmin):
    list_display = ('name','active','added')
    ordering = ('name',)
    #actions = ('sync',)
    form = forms.ExcludedFileEditForm


    def has_change_permission(self, request, obj=None):
        return True

    def has_add_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return True


class LeakMixin(object):
    list_display = ('account_name','repository_name', 'branch_name','commit','rule','risk_level','name')
    ordering = ('repository__account','repository','branch','commit__commit_id')
    list_filter = ('rule__category','repository', )
    #actions = ('sync',)
    readonly_fields = ('account_name','repository_name', 'branch_name','_commit','rule','risk_level','_file','line_number','name',"value","details")

    def account_name(self,obj):
        return obj.repository.account.name if obj else ""
    account_name.short_description = 'Account'

    def repository_name(self,obj):
        return obj.repository.name if obj else ""
    repository_name.short_description = 'Repository'

    def branch_name(self,obj):
        return obj.branch.name if obj else ""
    branch_name.short_description = 'Branch'

    def commit_id(self,obj):
        return obj.commit.commit_id if obj else ""
    commit_id.short_description = 'Commit'

    def risk_level(self,obj):
        return obj.rule.get_risk_level_display() if obj else None
    risk_level.short_description = 'Risk Level'

    def _commit(self,obj):
        if obj:
            return mark_safe("<A href='/admin/github/commit/{}/change/'>{}</A>".format(obj.commit.id,obj.commit))
        else:
            return ""
        return obj.rule.get_risk_level_display() if obj else None
    _commit.short_description = 'Commit'


    def _file(self,obj):
        if not obj:
            return ""
        if obj.rule.content_match or True:
            if obj.file.startswith("/"):
                return mark_safe('<a href="/github/fileview/{0}/{1}{2}" target="_blank_">{3}</a>'.format(obj.repository.id,obj.commit.id,filepath_to_uri(obj.file.replace('"','\"')),obj.file))
            else:
                return mark_safe('<a href="/github/fileview/{0}/{1}/{2}" target="_blank_">/{3}</a>'.format(obj.repository.id,obj.commit.id,filepath_to_uri(obj.file.replace('"','\"')),obj.file))
        else:
            return obj.file

    _file.short_description = 'File'

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Leak)
class LeakAdmin(LeakMixin,admin.ModelAdmin):
    pass

@admin.register(ExcludedLeak)
class ExcludedLeakAdmin(LeakMixin,admin.ModelAdmin):
    readonly_fields = ('account_name','repository_name', 'branch_name','commit','rule','excluded_rule','risk_level','_file','line_number','name',"value","details")

    def excluded_rule(self,obj):
        return mark_safe("<a href='/admin/github/leakrule/{}/change/'>{}</a>".format(obj.excluded_value.rule.id,obj.excluded_value.id)) if obj else ""
    excluded_rule.short_description = 'Excluded Rule'


