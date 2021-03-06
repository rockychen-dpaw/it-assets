from django.core.management.base import BaseCommand
from organisation.models import DepartmentUser
from registers.models import ITSystem
from registers.utils import ms_graph_sharepoint_users, ms_graph_sharepoint_it_systems


class Command(BaseCommand):
    help = 'Queries Sharepoint for the IT System Register and syncs it locally'

    def handle(self, *args, **options):
        self.stdout.write('Querying Microsoft Graph API for Sharepoint user information')
        sharepoint_users = ms_graph_sharepoint_users()

        # Create a dict of user emails using Id as the key.
        users_dict = {}
        for user in sharepoint_users:
            if 'EMail' in user:
                users_dict[user['id']] = user['EMail']

        self.stdout.write('Querying Microsoft Graph API for IT System Register')
        it_systems = ms_graph_sharepoint_it_systems()

        prod_systems = ITSystem.objects.filter(status__in=[0, 2])

        for system in it_systems:
            self.stdout.write('Checking {}'.format(system['Title']))
            system_id = system['Title'].split()[0]
            name = system['Title'].partition(' - ')[-1]
            update = False

            if ITSystem.objects.filter(system_id=system_id).exists():
                it_system = ITSystem.objects.get(system_id=system_id)
                prod_systems = prod_systems.exclude(pk=it_system.pk)
            else:
                self.stdout.write(self.style.WARNING('Failed to match {} - {}, creating new system'.format(system_id, name)))
                it_system = ITSystem.objects.create(system_id=system_id, name=name)
                prod_systems = prod_systems.exclude(pk=it_system.pk)

            # Name
            if name and name != it_system.name:
                it_system.name = name
                update = True
                self.stdout.write(self.style.SUCCESS('Changing {} name to {}'.format(it_system, name)))

            # Status
            status = system['Status']
            if status == 'Production' and status != it_system.get_status_display():
                it_system.status = 0
                update = True
                self.stdout.write(self.style.SUCCESS('Changing {} status to Production'.format(it_system)))
            elif status == 'Production (Legacy)' and status != it_system.get_status_display():
                it_system.status = 2
                update = True
                self.stdout.write(self.style.SUCCESS('Changing {} status to Production (Legacy)'.format(it_system)))
            elif status == 'Decommissioned' and status != it_system.get_status_display():
                it_system.status = 3
                update = True
                self.stdout.write(self.style.SUCCESS('Changing {} status to Decommissioned'.format(it_system)))

            # System owner
            if system['SystemOwnerLookupId']:
                owner_email = users_dict[system['SystemOwnerLookupId']]
            else:
                owner_email = None
            if owner_email:
                # Instead of the full email, split the local part off the domain and try using that.
                # This is due to some systems having users defined as e.g. firstname.lastname@DPaW.onmicrosoft.com
                # instead of using a DBCA email address.
                owner = owner_email.split('@')[0].lower()
                if DepartmentUser.objects.filter(email__istartswith=owner).exists():
                    # Change the system owner if reqd
                    du = DepartmentUser.objects.filter(email__istartswith=owner).first()
                    if du != it_system.owner:
                        it_system.owner = du
                        update = True
                        self.stdout.write(self.style.SUCCESS('Changing {} owner to {}'.format(it_system, du)))
                else:
                    # Warn about user not being found
                    self.stdout.write(self.style.WARNING('Owner {} not found ({})'.format(owner_email, it_system)))
            else:
                if it_system.owner:
                    # No owner - clear the owner value.
                    it_system.owner = None
                    update = True
                    self.stdout.write(self.style.WARNING('No owner recorded for {}, clearing'.format(it_system)))

            # Technology custodian
            if system['TechnicalCustodianLookupId']:
                custodian_email = users_dict[system['TechnicalCustodianLookupId']]
            else:
                custodian_email = None
            if custodian_email:
                # See above note about email.
                custodian = custodian_email.split('@')[0].lower()
                if DepartmentUser.objects.filter(email__istartswith=custodian).exists():
                    # Change the tech custodian if reqd
                    du = DepartmentUser.objects.filter(email__istartswith=custodian).first()
                    if du != it_system.technology_custodian:
                        it_system.technology_custodian = du
                        update = True
                        self.stdout.write(self.style.SUCCESS('Changing {} technology custodian to {}'.format(it_system, du)))
                else:
                    # Warn about user not being found
                    self.stdout.write(self.style.WARNING('Tech custodian {} not found ({})'.format(custodian_email, it_system)))
            else:
                if it_system.technology_custodian:
                    # No custodian - clear the value.
                    it_system.technology_custodian = None
                    update = True
                    self.stdout.write(self.style.WARNING('No tech custodian recorded for {}, clearing'.format(it_system)))

            # Information custodian
            if system['InformationCustodianLookupId']:
                info_email = users_dict[system['InformationCustodianLookupId']]
            else:
                info_email = None
            if info_email:
                # See above note about email.
                info = info_email.split('@')[0].lower()
                if DepartmentUser.objects.filter(email__istartswith=info).exists():
                    # Change the info custodian if reqd
                    du = DepartmentUser.objects.filter(email__istartswith=info).first()
                    if du != it_system.information_custodian:
                        it_system.information_custodian = du
                        update = True
                        self.stdout.write(self.style.SUCCESS('Changing {} info custodian to {}'.format(it_system, du)))
                else:
                    # Warn about user not being found
                    self.stdout.write(self.style.WARNING('Info custodian {} not found ({})'.format(info_email, it_system)))
            else:
                if it_system.information_custodian:
                    # No custodian - clear the value.
                    it_system.information_custodian = None
                    update = True
                    self.stdout.write(self.style.WARNING('No info custodian recorded for {}, clearing'.format(it_system)))

            # Seasonality
            if 'Seasonality' in system:
                season = system['Seasonality']
            else:
                season = None
            if season and season != it_system.get_seasonality_display():
                for i in ITSystem.SEASONALITY_CHOICES:
                    if season == i[1]:
                        it_system.seasonality = i[0]
                        update = True
                        self.stdout.write(self.style.SUCCESS('Changing {} seasonality to {}'.format(it_system, season)))

            # Availability
            if 'Availability' in system:
                avail = system['Availability']
            else:
                avail = None
            if avail and avail != it_system.get_availability_display():
                for i in ITSystem.AVAILABILITY_CHOICES:
                    if avail == i[1]:
                        it_system.availability = i[0]
                        update = True
                        self.stdout.write(self.style.SUCCESS('Changing {} availability to {}'.format(it_system, avail)))

            # Link
            if 'Link0' in system and system['Link0'] and system['Link0']['Url']:
                link = system['Link0']['Url'].strip()
            else:
                link = None
            if link != it_system.link:
                it_system.link = link
                update = True
                self.stdout.write(self.style.SUCCESS('Changing {} link to {}'.format(it_system, link)))

            # Description
            if 'Description' in system:
                desc = system['Description']
            else:
                desc = ''
            if desc != it_system.description:
                it_system.description = desc
                update = True
                self.stdout.write(self.style.SUCCESS('Changing {} description to {}'.format(it_system, desc)))

            # Finally, save any changes.
            if update:
                it_system.save()

        if prod_systems:
            self.stdout.write(self.style.WARNING('These systems not found in upload (status changed to Unknown): {}'.format(', '.join(i.name for i in prod_systems))))
            for it_system in prod_systems:
                it_system.status = 4
                it_system.save()

        self.stdout.write(self.style.SUCCESS('Completed'))
