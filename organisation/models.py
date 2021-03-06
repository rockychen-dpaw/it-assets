from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField, ArrayField, CIEmailField
from django.contrib.gis.db import models


class DepartmentUser(models.Model):
    """Represents a Department user. Maps to an object managed by Active Directory.
    """
    ACTIVE_FILTER = {'active': True, 'cost_centre__isnull': False, 'contractor': False}
    # The following choices are intended to match options in Ascender.
    ACCOUNT_TYPE_CHOICES = (
        (2, 'L1 User Account - Permanent'),
        (3, 'L1 User Account - Agency contract'),
        (0, 'L1 User Account - Department fixed-term contract'),
        (8, 'L1 User Account - Seasonal'),
        (6, 'L1 User Account - Vendor'),
        (7, 'L1 User Account - Volunteer'),
        (1, 'L1 User Account - Other/Alumni'),
        (11, 'L1 User Account - RoomMailbox'),
        (12, 'L1 User Account - EquipmentMailbox'),
        (10, 'L2 Service Account - System'),
        (5, 'L1 Group (shared) Mailbox - Shared account'),
        (9, 'L1 Role Account - Role-based account'),
        (4, 'Terminated'),
        (14, 'Unknown - AD disabled'),
        (15, 'Cleanup - Permanent'),
        (16, 'Unknown - AD active'),
    )
    # The following is a list of account type of normally exclude from user queries.
    # E.g. shared accounts, meeting rooms, terminated accounts, etc.
    ACCOUNT_TYPE_EXCLUDE = [4, 5, 9, 10, 11, 12, 14, 16]
    # The following is a list of account types set for individual staff/vendors,
    # i.e. no shared or role-based account types.
    # NOTE: it may not necessarily be the inverse of the previous list.
    ACCOUNT_TYPE_USER = [2, 3, 0, 8, 6, 7, 1]
    POSITION_TYPE_CHOICES = (
        (0, 'Full time'),
        (1, 'Part time'),
        (2, 'Casual'),
        (3, 'Other'),
    )

    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    # Fields directly related to the employee, which map to a field in Azure Active Directory.
    # The Azure AD field name is listed after each field.
    active = models.BooleanField(
        default=True, editable=False, help_text='Account is enabled/disabled within Active Directory.')  # AccountEnabled
    email = CIEmailField(unique=True, editable=False, help_text='Account primary email address')  # Mail
    name = models.CharField(
        max_length=128, verbose_name='display name', help_text='Format: [Given name] [Surname]')  # DisplayName
    given_name = models.CharField(
        max_length=128, null=True, blank=True,
        help_text='Legal first name (matches birth certificate/passport/etc.)')  # GivenName
    surname = models.CharField(
        max_length=128, null=True, blank=True,
        help_text='Legal surname (matches birth certificate/passport/etc.)')  # Surname
    title = models.CharField(
        max_length=128, null=True, blank=True,
        help_text='Occupation position title (should match Ascender position title)')  # JobTitle
    telephone = models.CharField(
        max_length=128, null=True, blank=True, help_text='Work telephone number')  # TelephoneNumber
    mobile_phone = models.CharField(
        max_length=128, null=True, blank=True, help_text='Work mobile number')  # Mobile
    manager = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='manages', help_text='Staff member who manages this employee')  # Manager
    cost_centre = models.ForeignKey(
        'organisation.CostCentre', on_delete=models.PROTECT, null=True, blank=True,
        help_text='Cost centre to which the employee currently belongs')  # CompanyName
    org_unit = models.ForeignKey(
        'organisation.OrgUnit', on_delete=models.PROTECT, null=True, blank=True,
        verbose_name='organisational unit',
        help_text="The organisational unit to which the employee belongs.")  # NOTE: no AAD field mapping.
    location = models.ForeignKey(
        'Location', on_delete=models.PROTECT, null=True, blank=True,
        help_text='Current physical workplace.')  # PhysicalDeliveryOfficeName, StreetAddress
    proxy_addresses = ArrayField(base_field=models.CharField(
        max_length=254, blank=True), blank=True, null=True, help_text='Email aliases')  # ProxyAddresses
    assigned_licences = ArrayField(base_field=models.CharField(
        max_length=254, blank=True), blank=True, null=True, help_text='Assigned Office 365 licences')  # AssignedLicenses
    mail_nickname = models.CharField(max_length=128, null=True, blank=True)  # MailNickName
    dir_sync_enabled = models.NullBooleanField(default=None)  # DirSyncEnabled - indicates that the Azure user is synced to on-prem AD.

    # Metadata fields with no direct equivalent in AD.
    # They are used for internal reporting and the address book.
    preferred_name = models.CharField(max_length=256, null=True, blank=True)
    extension = models.CharField(
        max_length=128, null=True, blank=True, verbose_name='VoIP extension')
    home_phone = models.CharField(max_length=128, null=True, blank=True)
    other_phone = models.CharField(max_length=128, null=True, blank=True)
    position_type = models.PositiveSmallIntegerField(
        choices=POSITION_TYPE_CHOICES, null=True, blank=True,
        help_text='Employee position working arrangement (Ascender employment status)')
    employee_id = models.CharField(
        max_length=128, null=True, unique=True, blank=True, verbose_name='Employee ID',
        help_text='Ascender employee number')
    name_update_reference = models.CharField(
        max_length=512, null=True, blank=True, verbose_name='update reference',
        help_text='Reference for name/CC change request')
    vip = models.BooleanField(
        default=False,
        help_text="An individual who carries out a critical role for the department")
    executive = models.BooleanField(
        default=False, help_text="An individual who is an executive")
    contractor = models.BooleanField(
        default=False,
        help_text="An individual who is an external contractor (does not include agency contract staff)")
    notes = models.TextField(
        null=True, blank=True,
        help_text='Records relevant to any AD account extension, expiry or deletion (e.g. ticket #).')
    working_hours = models.TextField(
        null=True, blank=True, help_text="Description of normal working hours")
    account_type = models.PositiveSmallIntegerField(
        choices=ACCOUNT_TYPE_CHOICES, null=True, blank=True,
        help_text='Employee network account status')
    security_clearance = models.BooleanField(
        default=False, verbose_name='security clearance granted',
        help_text='''Security clearance approved by CC Manager (confidentiality
        agreement, referee check, police clearance, etc.''')
    shared_account = models.BooleanField(
        default=False, editable=False, help_text='Automatically set from account type.')
    username = models.CharField(
        max_length=128, editable=False, blank=True, null=True, help_text='Pre-Windows 2000 login username.')  # SamAccountName in onprem AD

    # Cache of Ascender data
    ascender_data = JSONField(null=True, blank=True, editable=False, help_text="Cache of staff Ascender data")
    ascender_data_updated = models.DateTimeField(null=True, editable=False)
    # Cache of on-premise AD data
    ad_guid = models.CharField(
        max_length=48, unique=True, null=True, blank=True, verbose_name="AD GUID",
        help_text="On-premise AD ObjectGUID")
    ad_data = JSONField(null=True, blank=True, editable=False, help_text="Cache of on-premise AD data")
    ad_data_updated = models.DateTimeField(null=True, editable=False)
    # Cache of Azure AD data
    azure_guid = models.CharField(
        max_length=48, unique=True, null=True, blank=True, verbose_name="Azure GUID",
        editable=False, help_text="Azure AD ObjectId")
    azure_ad_data = JSONField(null=True, blank=True, editable=False, help_text="Cache of Azure AD data")
    azure_ad_data_updated = models.DateTimeField(null=True, editable=False)

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        """Override the save method with additional business logic.
        """
        if self.employee_id:
            if (self.employee_id.lower() == "n/a") or (self.employee_id.strip() == ''):
                self.employee_id = None
        if self.account_type in [5, 9, 10]:  # Shared/role-based/system account types.
            self.shared_account = True
        super(DepartmentUser, self).save(*args, **kwargs)

    @property
    def group_unit(self):
        """Return the group-level org unit, as seen in the primary address book view.
        """
        if self.org_unit and self.org_unit.division_unit:
            return self.org_unit.division_unit
        return self.org_unit

    def get_office_licence(self):
        """Return Microsoft 365 licence description consistent with other OIM communications.
        """
        if self.assigned_licences:
            if 'MICROSOFT 365 E5' in self.assigned_licences:
                return 'On-premise'
            elif 'OFFICE 365 E5' in self.assigned_licences:
                return 'On-premise'
            elif 'OFFICE 365 E1' in self.assigned_licences:
                return 'Cloud'
        return None

    def get_full_name(self):
        # Return given_name and surname, with a space in between.
        full_name = '{} {}'.format(self.given_name, self.surname)
        return full_name.strip()

    def generate_ad_actions(self):
        """For this object, generate ADAction objects that specify the changes which need to be
        carried out in order to synchronise AD (onprem/Azure) with IT Assets.
        """
        actions = []

        if self.dir_sync_enabled:
            # On-prem AD
            if not self.ad_guid or not self.ad_data:
                return []

            if 'DisplayName' in self.ad_data and self.ad_data['DisplayName'] != self.name:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='DisplayName',
                    ad_field_value=self.ad_data['DisplayName'],
                    field='name',
                    field_value=self.name,
                    completed=None,
                )
                actions.append(action)

            if 'GivenName' in self.ad_data and self.ad_data['GivenName'] != self.given_name:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='GivenName',
                    ad_field_value=self.ad_data['GivenName'],
                    field='given_name',
                    field_value=self.given_name,
                    completed=None,
                )
                actions.append(action)

            if 'Surname' in self.ad_data and self.ad_data['Surname'] != self.surname:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='Surname',
                    ad_field_value=self.ad_data['Surname'],
                    field='surname',
                    field_value=self.surname,
                    completed=None,
                )
                actions.append(action)

            if 'Title' in self.ad_data and self.ad_data['Title'] != self.title:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='Title',
                    ad_field_value=self.ad_data['Title'],
                    field='title',
                    field_value=self.title,
                    completed=None,
                )
                actions.append(action)

            if 'telephoneNumber' in self.ad_data and self.ad_data['telephoneNumber'] != self.telephone:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='telephoneNumber',
                    ad_field_value=self.ad_data['telephoneNumber'],
                    field='telephone',
                    field_value=self.telephone,
                    completed=None,
                )
                actions.append(action)

            if 'Mobile' in self.ad_data and self.ad_data['Mobile'] != self.mobile_phone:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='Mobile',
                    ad_field_value=self.ad_data['Mobile'],
                    field='mobile_phone',
                    field_value=self.mobile_phone,
                    completed=None,
                )
                actions.append(action)

            if self.cost_centre and 'Company' in self.ad_data and self.ad_data['Company'] != self.cost_centre.code:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='Company',
                    ad_field_value=self.ad_data['Company'],
                    field='cost_centre',
                    field_value=self.cost_centre.code,
                    completed=None,
                )
                actions.append(action)

            if self.location and 'physicalDeliveryOfficeName' in self.ad_data and self.ad_data['physicalDeliveryOfficeName'] != self.location.name:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='physicalDeliveryOfficeName',
                    ad_field_value=self.ad_data['physicalDeliveryOfficeName'],
                    field='location',
                    field_value=self.location.name,
                    completed=None,
                )
                actions.append(action)

            if 'EmployeeID' in self.ad_data and self.ad_data['EmployeeID'] != self.employee_id:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='EmployeeID',
                    ad_field_value=self.ad_data['EmployeeID'],
                    field='employee_id',
                    field_value=self.employee_id,
                    completed=None,
                )
                actions.append(action)

            # TODO: manager
        else:
            # Azure AD
            if not self.azure_guid or not self.azure_ad_data:
                return []

            if 'displayName' in self.azure_ad_data and self.azure_ad_data['displayName'] != self.name:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='displayName',
                    ad_field_value=self.azure_ad_data['displayName'],
                    field='name',
                    field_value=self.name,
                    completed=None,
                )
                actions.append(action)

            if 'givenName' in self.azure_ad_data and self.azure_ad_data['givenName'] != self.given_name:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='givenName',
                    ad_field_value=self.azure_ad_data['givenName'],
                    field='given_name',
                    field_value=self.given_name,
                    completed=None,
                )
                actions.append(action)

            if 'surname' in self.azure_ad_data and self.azure_ad_data['surname'] != self.surname:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='Surname',
                    ad_field_value=self.azure_ad_data['surname'],
                    field='surname',
                    field_value=self.surname,
                    completed=None,
                )
                actions.append(action)

            if 'jobTitle' in self.azure_ad_data and self.azure_ad_data['jobTitle'] != self.title:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='jobTitle',
                    ad_field_value=self.azure_ad_data['jobTitle'],
                    field='title',
                    field_value=self.title,
                    completed=None,
                )
                actions.append(action)

            if 'telephoneNumber' in self.azure_ad_data and self.azure_ad_data['telephoneNumber'] != self.telephone:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='telephoneNumber',
                    ad_field_value=self.azure_ad_data['telephoneNumber'],
                    field='telephone',
                    field_value=self.telephone,
                    completed=None,
                )
                actions.append(action)

            if 'mobilePhone' in self.azure_ad_data and self.azure_ad_data['mobilePhone'] != self.mobile_phone:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='mobilePhone',
                    ad_field_value=self.azure_ad_data['mobilePhone'],
                    field='mobile_phone',
                    field_value=self.mobile_phone,
                    completed=None,
                )
                actions.append(action)

            if self.cost_centre and 'companyName' in self.azure_ad_data and self.azure_ad_data['companyName'] != self.cost_centre.code:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='companyName',
                    ad_field_value=self.azure_ad_data['companyName'],
                    field='cost_centre',
                    field_value=self.cost_centre.code,
                    completed=None,
                )
                actions.append(action)

            if self.location and 'officeLocation' in self.azure_ad_data and self.azure_ad_data['officeLocation'] != self.location.name:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='officeLocation',
                    ad_field_value=self.azure_ad_data['officeLocation'],
                    field='location',
                    field_value=self.location.name,
                    completed=None,
                )
                actions.append(action)

            if 'employeeId' in self.azure_ad_data and self.azure_ad_data['employeeId'] != self.employee_id:
                action, created = ADAction.objects.get_or_create(
                    department_user=self,
                    action_type='Change account field',
                    ad_field='employeeId',
                    ad_field_value=self.azure_ad_data['employeeId'],
                    field='employee_id',
                    field_value=self.employee_id,
                    completed=None,
                )
                actions.append(action)

        return actions

    def audit_ad_actions(self):
        """For this DepartmentUser object, check any incomplete ADAction
        objects that specify changes to be made for the AD user. If the ADAction is no longer
        required (e.g. changes have been completed/reverted), delete the ADAction object.
        """
        actions = ADAction.objects.filter(department_user=self, completed__isnull=True)

        if self.dir_sync_enabled:
            # Onprem AD
            if not self.ad_guid or not self.ad_data:
                return

            for action in actions:
                if action.field == 'name' and self.ad_data['DisplayName'] == self.name:
                    action.delete()
                elif action.field == 'given_name' and self.ad_data['GivenName'] == self.given_name:
                    action.delete()
                elif action.field == 'surname' and self.ad_data['Surname'] == self.surname:
                    action.delete()
                elif action.field == 'title' and self.ad_data['Title'] == self.title:
                    action.delete()
                elif action.field == 'telephone' and self.ad_data['telephoneNumber'] == self.telephone:
                    action.delete()
                elif action.field == 'mobile_phone' and self.ad_data['Mobile'] == self.mobile_phone:
                    action.delete()
                elif action.field == 'cost_centre' and self.ad_data['Company'] == self.cost_centre.code:
                    action.delete()
                elif action.field == 'location' and self.ad_data['physicalDeliveryOfficeName'] == self.location.name:
                    action.delete()
                elif action.field == 'employee_id' and self.ad_data['EmployeeID'] == self.employee_id:
                    action.delete()
        else:
            # Azure AD
            if not self.azure_guid or not self.azure_ad_data:
                return

            for action in actions:
                if action.field == 'name' and self.azure_ad_data['displayName'] == self.name:
                    action.delete()
                elif action.field == 'given_name' and self.azure_ad_data['givenName'] == self.given_name:
                    action.delete()
                elif action.field == 'surname' and self.azure_ad_data['surname'] == self.surname:
                    action.delete()
                elif action.field == 'title' and self.azure_ad_data['jobTitle'] == self.title:
                    action.delete()
                elif action.field == 'telephone' and self.azure_ad_data['telephoneNumber'] == self.telephone:
                    action.delete()
                elif action.field == 'mobile_phone' and self.azure_ad_data['mobilePhone'] == self.mobile_phone:
                    action.delete()
                elif action.field == 'cost_centre' and self.azure_ad_data['companyName'] == self.cost_centre.code:
                    action.delete()
                elif action.field == 'location' and self.azure_ad_data['officeLocation'] == self.location.name:
                    action.delete()
                elif action.field == 'employee_id' and self.azure_ad_data['employeeId'] == self.employee_id:
                    action.delete()


ACTION_TYPE_CHOICES = (
    ('Change email', 'Change email'),  # Separate from 'change field' because this is a significant operation.
    ('Change account field', 'Change account field'),
    ('Disable account', 'Disable account'),
    ('Enable account', 'Enable account'),
)
# This dict maps Azure AD field names to onprem AD field names.
AZURE_ONPREM_FIELD_MAP = {
    'AccountEnabled': 'Enabled',
    'Mail': 'EmailAddress',
    'JobTitle': 'Title',
    'TelephoneNumber': 'OfficePhone',
    'Mobile': 'MobilePhone',
    'CompanyName': 'Company',
}


class ADAction(models.Model):
    """Represents a single "action" or change that needs to be carried out to the Active Directory
    object which matches a DepartmentUser object.
    """
    created = models.DateTimeField(auto_now_add=True)
    department_user = models.ForeignKey(DepartmentUser, on_delete=models.CASCADE)
    action_type = models.CharField(max_length=128, choices=ACTION_TYPE_CHOICES)
    ad_field = models.CharField(max_length=128, blank=True, null=True, help_text='Name of the field in Active Directory')
    ad_field_value = models.TextField(blank=True, null=True, help_text='Value of the field in Active Directory')
    field = models.CharField(max_length=128, blank=True, null=True, help_text='Name of the field in IT Assets')
    field_value = models.TextField(blank=True, null=True, help_text='Value of the field in IT Assets')
    completed = models.DateTimeField(null=True, blank=True, editable=False)
    completed_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True, editable=False)

    class Meta:
        verbose_name = 'AD action'
        verbose_name_plural = 'AD actions'

    def __str__(self):
        return '{}: {} ({} -> {})'.format(
            self.department_user.azure_guid, self.action_type, self.ad_field, self.field_value
        )

    @property
    def azure_guid(self):
        return self.department_user.azure_guid

    @property
    def ad_guid(self):
        return self.department_user.ad_guid

    @property
    def action(self):
        return '{} {} to {}'.format(self.action_type, self.ad_field, self.field_value)


class Location(models.Model):
    """A model to represent a physical location.
    """
    #VOIP_PLATFORM_CHOICES = (
    #    ('3CX', '3CX'),
    #    ('CUCM', 'CUCM'),
    #    ('Teams', 'Teams'),
    #)

    name = models.CharField(max_length=256, unique=True)
    manager = models.ForeignKey(
        DepartmentUser, on_delete=models.PROTECT, null=True, blank=True,
        related_name='location_manager')
    address = models.TextField(unique=True, blank=True)
    pobox = models.TextField(blank=True, verbose_name='PO Box')
    phone = models.CharField(max_length=128, null=True, blank=True)
    fax = models.CharField(max_length=128, null=True, blank=True)
    email = models.CharField(max_length=128, null=True, blank=True)
    point = models.PointField(null=True, blank=True)
    url = models.CharField(
        max_length=2000,
        help_text='URL to webpage with more information',
        null=True,
        blank=True)
    bandwidth_url = models.CharField(
        max_length=2000,
        help_text='URL to prtg graph of bw utilisation',
        null=True,
        blank=True)
    ascender_code = models.CharField(max_length=16, null=True, blank=True, unique=True)
    active = models.BooleanField(default=True)
    #voip_platform = models.CharField(
    #    max_length=128, null=True, blank=True, choices=VOIP_PLATFORM_CHOICES)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name

    def as_dict(self):
        return {k: getattr(self, k) for k in (
            'id', 'name', 'address', 'pobox', 'phone', 'fax', 'email') if getattr(self, k)}


class OrgUnit(models.Model):
    """Represents an element within the Department organisational hierarchy.
    """
    TYPE_CHOICES = (
        (0, 'Department (Tier one)'),
        (1, 'Division (Tier two)'),
        (11, 'Division'),
        (9, 'Group'),
        (2, 'Branch'),
        (7, 'Section'),
        (3, 'Region'),
        (6, 'District'),
        (8, 'Unit'),
        (5, 'Office'),
        (10, 'Work centre'),
    )
    TYPE_CHOICES_DICT = dict(TYPE_CHOICES)
    unit_type = models.PositiveSmallIntegerField(choices=TYPE_CHOICES)
    name = models.CharField(max_length=256)
    acronym = models.CharField(max_length=16, null=True, blank=True)
    manager = models.ForeignKey(
        DepartmentUser, on_delete=models.PROTECT, null=True, blank=True)
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, null=True, blank=True)
    division_unit = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='division_orgunits',
        help_text='Division-level unit to which this unit belongs',
    )
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)

    def cc(self):
        return ', '.join([str(x) for x in self.costcentre_set.all()])

    def __str__(self):
        return self.name


DIVISION_CHOICES = (
    ("BCS", "DBCA Biodiversity and Conservation Science"),
    ("BGPA", "Botanic Gardens and Parks Authority"),
    ("CBS", "DBCA Corporate and Business Services"),
    ("CPC", "Conservation and Parks Commission"),
    ("ODG", "Office of the Director General"),
    ("PWS", "Parks and Wildlife Service"),
    ("RIA", "Rottnest Island Authority"),
    ("ZPA", "Zoological Parks Authority"),
)


class CostCentre(models.Model):
    """Models the details of a Department cost centre / chart of accounts.
    """
    code = models.CharField(max_length=16, unique=True)
    chart_acct_name = models.CharField(
        max_length=256, blank=True, null=True, verbose_name='chart of accounts name')
    division_name = models.CharField(max_length=128, choices=DIVISION_CHOICES, null=True, blank=True)
    org_position = models.ForeignKey(
        OrgUnit, on_delete=models.PROTECT, blank=True, null=True)
    manager = models.ForeignKey(
        DepartmentUser, on_delete=models.PROTECT, related_name='manage_ccs',
        null=True, blank=True)
    business_manager = models.ForeignKey(
        DepartmentUser, on_delete=models.PROTECT, related_name='bmanage_ccs',
        help_text='Business Manager', null=True, blank=True)
    admin = models.ForeignKey(
        DepartmentUser, on_delete=models.PROTECT, related_name='admin_ccs',
        help_text='Adminstration Officer', null=True, blank=True)
    tech_contact = models.ForeignKey(
        DepartmentUser, on_delete=models.PROTECT, related_name='tech_ccs',
        help_text='Technical Contact', null=True, blank=True)
    ascender_code = models.CharField(max_length=16, null=True, blank=True, unique=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ('code',)

    def __str__(self):
        return self.code
