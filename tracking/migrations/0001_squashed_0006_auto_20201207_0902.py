# Generated by Django 2.2.21 on 2021-05-10 02:08

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    replaces = [('tracking', '0001_initial'), ('tracking', '0002_licensingrule'), ('tracking', '0003_auto_20181005_1432'), ('tracking', '0004_computer_pdq_id'), ('tracking', '0005_auto_20200908_1207'), ('tracking', '0006_auto_20201207_0902')]

    initial = True

    dependencies = [
        ('organisation', '0001_initial'),
        ('organisation', '0007_auto_20180829_1733'),
    ]

    operations = [
        migrations.CreateModel(
            name='EC2Instance',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_created', models.DateTimeField(auto_now_add=True)),
                ('date_updated', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=200, verbose_name='Instance Name')),
                ('ec2id', models.CharField(max_length=200, unique=True, verbose_name='EC2 Instance ID')),
                ('launch_time', models.DateTimeField(blank=True, editable=False, null=True)),
                ('next_state', models.BooleanField(default=True, help_text='Checked is on, unchecked is off')),
                ('running', models.BooleanField(default=True)),
                ('agent_version', models.CharField(blank=True, max_length=128, null=True, verbose_name='SSM agent version')),
                ('tags', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=dict, help_text='AWS tags (key value pairs).', null=True)),
            ],
            options={
                'verbose_name': 'EC2 instance',
            },
        ),
        migrations.CreateModel(
            name='FreshdeskContact',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('active', models.BooleanField(default=False, help_text='Set to true if the contact has been verified.')),
                ('address', models.CharField(blank=True, max_length=512, null=True)),
                ('contact_id', models.BigIntegerField(help_text='ID of the contact.', unique=True)),
                ('created_at', models.DateTimeField(blank=True, null=True)),
                ('custom_fields', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=dict, help_text='Key value pairs containing the names and values of custom fields.', null=True)),
                ('description', models.TextField(blank=True, help_text='A short description of the contact.', null=True)),
                ('email', models.CharField(blank=True, help_text='Primary email address of the contact.', max_length=256, null=True, unique=True)),
                ('job_title', models.CharField(blank=True, help_text='Job title of the contact.', max_length=256, null=True)),
                ('language', models.CharField(blank=True, help_text='Language of the contact.', max_length=256, null=True)),
                ('mobile', models.CharField(blank=True, help_text='Mobile number of the contact.', max_length=256, null=True)),
                ('name', models.CharField(blank=True, help_text='Name of the contact.', max_length=256, null=True)),
                ('other_emails', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, help_text='Additional emails associated with the contact. An array of strings.', null=True)),
                ('phone', models.CharField(blank=True, help_text='Phone number of the contact.', max_length=256, null=True)),
                ('tags', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, help_text='Tags that have been associated with the contact. An array of strings.', null=True)),
                ('time_zone', models.CharField(blank=True, help_text='Time zone in which the contact resides.', max_length=256, null=True)),
                ('updated_at', models.DateTimeField(blank=True, help_text='Contact updated timestamp.', null=True)),
                ('du_user', models.ForeignKey(blank=True, help_text='Department User that is represented by this Freshdesk contact.', null=True, on_delete=django.db.models.deletion.SET_NULL, to='organisation.DepartmentUser')),
            ],
        ),
        migrations.CreateModel(
            name='FreshdeskTicket',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('attachments', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, help_text='Ticket attachments. An array of objects.', null=True)),
                ('cc_emails', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, help_text='Email address added in the "cc" field of the incoming ticket email. An array of strings.', null=True)),
                ('created_at', models.DateTimeField(blank=True, null=True)),
                ('custom_fields', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=dict, help_text='Key value pairs containing the names and values of custom fields.', null=True)),
                ('deleted', models.BooleanField(default=False, help_text='Set to true if the ticket has been deleted/trashed.')),
                ('description', models.TextField(blank=True, help_text='HTML content of the ticket.', null=True)),
                ('description_text', models.TextField(blank=True, help_text='Content of the ticket in plain text.', null=True)),
                ('due_by', models.DateTimeField(blank=True, help_text='Timestamp that denotes when the ticket is due to be resolved.', null=True)),
                ('email', models.CharField(blank=True, help_text='Email address of the requester.', max_length=256, null=True)),
                ('fr_due_by', models.DateTimeField(blank=True, help_text='Timestamp that denotes when the first response is due.', null=True)),
                ('fr_escalated', models.BooleanField(default=False, help_text='Set to true if the ticket has been escalated as the result of first response time being breached.')),
                ('fwd_emails', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, help_text='Email address(e)s added while forwarding a ticket. An array of strings.', null=True)),
                ('group_id', models.BigIntegerField(blank=True, help_text='ID of the group to which the ticket has been assigned.', null=True)),
                ('is_escalated', models.BooleanField(default=False, help_text='Set to true if the ticket has been escalated for any reason.')),
                ('name', models.CharField(blank=True, help_text='Name of the requester.', max_length=256, null=True)),
                ('phone', models.CharField(blank=True, help_text='Phone number of the requester.', max_length=256, null=True)),
                ('priority', models.IntegerField(blank=True, help_text='Priority of the ticket.', null=True)),
                ('reply_cc_emails', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, help_text='Email address added while replying to a ticket. An array of strings.', null=True)),
                ('requester_id', models.BigIntegerField(blank=True, help_text='User ID of the requester.', null=True)),
                ('responder_id', models.BigIntegerField(blank=True, help_text='ID of the agent to whom the ticket has been assigned.', null=True)),
                ('source', models.IntegerField(blank=True, help_text='The channel through which the ticket was created.', null=True)),
                ('spam', models.BooleanField(default=False, help_text='Set to true if the ticket has been marked as spam.')),
                ('status', models.IntegerField(blank=True, help_text='Status of the ticket.', null=True)),
                ('subject', models.TextField(blank=True, help_text='Subject of the ticket.', null=True)),
                ('tags', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, help_text='Tags that have been associated with the ticket. An array of strings.', null=True)),
                ('ticket_id', models.IntegerField(help_text='Unique ID of the ticket in Freshdesk.', unique=True)),
                ('to_emails', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, help_text='Email addresses to which the ticket was originally sent. An array of strings.', null=True)),
                ('type', models.CharField(blank=True, help_text='Ticket type.', max_length=256, null=True)),
                ('updated_at', models.DateTimeField(blank=True, help_text='Ticket updated timestamp.', null=True)),
                ('du_requester', models.ForeignKey(blank=True, help_text='Department User who raised the ticket.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='du_requester', to='organisation.DepartmentUser')),
                ('du_responder', models.ForeignKey(blank=True, help_text='Department User to whom the ticket is assigned.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='du_responder', to='organisation.DepartmentUser')),
                ('freshdesk_requester', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='freshdesk_requester', to='tracking.FreshdeskContact')),
                ('freshdesk_responder', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='freshdesk_responder', to='tracking.FreshdeskContact')),
            ],
        ),
        migrations.CreateModel(
            name='LicensingRule',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('product_name', models.CharField(max_length=256)),
                ('publisher_name', models.CharField(max_length=256)),
                ('regex', models.CharField(max_length=2048)),
                ('license', models.SmallIntegerField(choices=[(1, 'Freeware'), (2, 'Open Source'), (3, 'Commercial - To be decommissioned'), (4, 'Commercial - License required'), (5, 'Commercial - Managed by OIM')])),
            ],
        ),
        migrations.CreateModel(
            name='FreshdeskConversation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('attachments', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, help_text='Ticket attachments. An array of objects.', null=True)),
                ('body', models.TextField(blank=True, help_text='HTML content of the conversation.', null=True)),
                ('body_text', models.TextField(blank=True, help_text='Content of the conversation in plain text.', null=True)),
                ('cc_emails', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, help_text='Email address added in the "cc" field of the conversation. An array of strings.', null=True)),
                ('created_at', models.DateTimeField(blank=True, null=True)),
                ('conversation_id', models.BigIntegerField(help_text='Unique ID of the conversation in Freshdesk.', unique=True)),
                ('from_email', models.CharField(blank=True, max_length=256, null=True)),
                ('incoming', models.BooleanField(default=False, help_text='Set to true if a particular conversation should appear as being created from outside.')),
                ('private', models.BooleanField(default=False, help_text='Set to true if the note is private.')),
                ('source', models.IntegerField(blank=True, help_text='Denotes the type of the conversation.', null=True)),
                ('ticket_id', models.IntegerField(help_text='ID of the ticket to which this conversation is being added.')),
                ('to_emails', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, help_text='Email addresses of agents/users who need to be notified about this conversation. An array of strings.', null=True)),
                ('updated_at', models.DateTimeField(blank=True, help_text='Ticket updated timestamp.', null=True)),
                ('user_id', models.BigIntegerField(help_text='ID of the agent/user who is adding the conversation.')),
                ('du_user', models.ForeignKey(blank=True, help_text='Department User who is adding to the conversation.', null=True, on_delete=django.db.models.deletion.SET_NULL, to='organisation.DepartmentUser')),
                ('freshdesk_contact', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='tracking.FreshdeskContact')),
                ('freshdesk_ticket', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='tracking.FreshdeskTicket')),
            ],
        ),
        migrations.CreateModel(
            name='Computer',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_created', models.DateTimeField(auto_now_add=True)),
                ('date_updated', models.DateTimeField(auto_now=True)),
                ('hostname', models.CharField(max_length=2048)),
                ('sam_account_name', models.CharField(blank=True, max_length=32, null=True, unique=True, verbose_name='sAMAccountName')),
                ('domain_bound', models.BooleanField(default=False)),
                ('ad_guid', models.CharField(blank=True, max_length=48, null=True, unique=True, verbose_name='AD GUID')),
                ('ad_dn', models.CharField(blank=True, max_length=512, null=True, unique=True, verbose_name='AD distinguished name')),
                ('manufacturer', models.CharField(blank=True, max_length=128, null=True)),
                ('model', models.CharField(blank=True, max_length=128, null=True)),
                ('chassis', models.CharField(blank=True, max_length=128, null=True)),
                ('serial_number', models.CharField(blank=True, max_length=128, null=True)),
                ('os_name', models.CharField(blank=True, max_length=128, null=True, verbose_name='OS name')),
                ('os_version', models.CharField(blank=True, max_length=128, null=True, verbose_name='OS version')),
                ('os_service_pack', models.CharField(blank=True, max_length=128, null=True, verbose_name='OS service pack')),
                ('os_arch', models.CharField(blank=True, max_length=128, null=True, verbose_name='OS architecture')),
                ('cpu', models.CharField(blank=True, max_length=128, null=True)),
                ('cpu_count', models.PositiveSmallIntegerField(blank=True, default=0, null=True)),
                ('cpu_cores', models.PositiveSmallIntegerField(blank=True, default=0, null=True)),
                ('memory', models.BigIntegerField(blank=True, default=0, null=True)),
                ('last_ad_login_username', models.CharField(blank=True, max_length=256, null=True)),
                ('last_ad_login_date', models.DateField(blank=True, null=True)),
                ('date_pdq_updated', models.DateTimeField(blank=True, null=True)),
                ('date_ad_updated', models.DateTimeField(blank=True, null=True)),
                ('ec2_instance', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='tracking.EC2Instance', verbose_name='EC2 instance')),
                ('location', models.ForeignKey(blank=True, help_text='Physical location', null=True, on_delete=django.db.models.deletion.SET_NULL, to='organisation.Location')),
                ('managed_by', models.ForeignKey(blank=True, help_text='"Official" device owner/manager (set in AD).', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='computers_managed', to='organisation.DepartmentUser')),
                ('probable_owner', models.ForeignKey(blank=True, help_text='Automatically-generated "most probable" device owner.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='computers_probably_owned', to='organisation.DepartmentUser')),
                ('date_ad_created', models.DateTimeField(blank=True, null=True)),
                ('date_pdq_last_seen', models.DateTimeField(blank=True, null=True)),
                ('last_login', models.ForeignKey(blank=True, help_text='User last seen logged on', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='computers_last_login', to='organisation.DepartmentUser')),
                ('pdq_id', models.PositiveIntegerField(null=True, unique=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Mobile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_created', models.DateTimeField(auto_now_add=True)),
                ('date_updated', models.DateTimeField(auto_now=True)),
                ('ad_guid', models.CharField(max_length=48, null=True, unique=True)),
                ('ad_dn', models.CharField(max_length=512, null=True, unique=True)),
                ('model', models.CharField(max_length=128, null=True)),
                ('os_name', models.CharField(max_length=128, null=True)),
                ('identity', models.CharField(max_length=512, null=True, unique=True)),
                ('serial_number', models.CharField(max_length=128, null=True)),
                ('imei', models.CharField(max_length=64, null=True)),
                ('last_sync', models.DateTimeField(null=True)),
                ('registered_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='organisation.DepartmentUser')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
