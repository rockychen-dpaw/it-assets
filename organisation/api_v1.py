from dateutil.parser import parse
from django.conf import settings
from django.db.models import Q
from django.urls import path, re_path
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
import json
import pytz
from restless.constants import OK
from restless.dj import DjangoResource
from restless.exceptions import BadRequest
from restless.preparers import FieldsPreparer
from restless.resources import skip_prepare
from restless.utils import MoreTypesJSONEncoder

from itassets.utils import FieldsFormatter, CSVDjangoResource
from .models import DepartmentUser, Location, OrgUnit, CostCentre


ACCOUNT_TYPE_DICT = dict(DepartmentUser.ACCOUNT_TYPE_CHOICES)
TIMEZONE = pytz.timezone(settings.TIME_ZONE)


def format_fileField(request, value):
    if value:
        return request.build_absolute_uri('{}{}'.format(settings.MEDIA_URL, value))
    else:
        return value


def format_position_type(request, value):
    if value is not None:
        position_type = dict(DepartmentUser.POSITION_TYPE_CHOICES)
        return position_type[value]
    else:
        return value


def format_account_type(request, value):
    if value is not None:
        return ACCOUNT_TYPE_DICT[value]
    else:
        return value


def format_location(request, value):
    if value is not None:
        location = Location.objects.get(pk=value)
        return location.as_dict()
    else:
        return None


def format_cost_centre(request, value):
    if value is not None:
        cc = CostCentre.objects.get(pk=value)
        return {
            'code': cc.code,
            'division': cc.get_division_name_display() if cc.division_name else '',
        }
    else:
        return None


def format_manager(request, value):
    if value is not None:
        manager = DepartmentUser.objects.get(pk=value)
        return {'name': manager.name, 'email': manager.email}
    else:
        return None


def format_org_unit(request, value):
    if value is not None:
        return OrgUnit.objects.get(pk=value).name
    else:
        return None


class DepartmentUserResource(DjangoResource):
    """An API Resource class to represent DepartmentUser objects.
    """
    COMPACT_ARGS = (
        'pk', 'name', 'title', 'email', 'telephone',
        'mobile_phone', 'extension', 'cost_centre',
        'manager', 'employee_id', 'location', 'preferred_name',
    )
    VALUES_ARGS = COMPACT_ARGS + (
        'active', 'given_name', 'surname', 'home_phone', 'other_phone',
        'position_type', 'account_type', 'shared_account', 'org_unit',
    )
    MINIMAL_ARGS = (
        'pk', 'name', 'preferred_name', 'title', 'email', 'telephone', 'mobile_phone',
    )

    formatters = FieldsFormatter(formatters={
        'position_type': format_position_type,
        'account_type': format_account_type,
        'location': format_location,
        'cost_centre': format_cost_centre,
        'manager': format_manager,
        'org_unit': format_org_unit,
    })

    def __init__(self, *args, **kwargs):
        super(DepartmentUserResource, self).__init__(*args, **kwargs)
        self.http_methods.update({
            'list_fast': {'GET': 'list_fast'},
            'list_licences': {'GET': 'list_licences'},
        })

    @classmethod
    def urls(self, name_prefix=None):
        """Override the DjangoResource ``urls`` class method so the detail view
        accepts a GUID parameter instead of PK.
        """
        return [
            path('', self.as_list(), name=self.build_url_name('list', name_prefix)),
            path('fast/', self.as_view('list_fast'), name=self.build_url_name('list_fast', name_prefix)),
            path('licences/', self.as_view('list_licences'), name=self.build_url_name('list_licences', name_prefix)),
            re_path(r'^(?P<guid>[0-9A-Za-z-_@\'&\.]+)/$', self.as_detail(), name=self.build_url_name('detail', name_prefix)),
        ]

    def build_response(self, data, status=OK):
        resp = super(DepartmentUserResource, self).build_response(data, status)
        # Require a short caching expiry for certain request types (if defined).
        if settings.API_RESPONSE_CACHE_SECONDS:
            if any(k in self.request.GET for k in ['email', 'compact', 'minimal']):
                resp['Cache-Control'] = 'max-age={}, public'.format(settings.API_RESPONSE_CACHE_SECONDS)
        return resp

    def is_authenticated(self):
        # We offload auth to the external service; assume all requests are legitimate.
        return True

    def list_licences(self):
        # Return active users having an E5 or E1 licence assigned.
        users = DepartmentUser.objects.filter(active=True)
        users = users.filter(
            Q(assigned_licences__contains=['MICROSOFT 365 E5']) |
            Q(assigned_licences__contains=['OFFICE 365 E5']) |
            Q(assigned_licences__contains=['OFFICE 365 E1'])
        )
        users = users.order_by('name')
        user_values = []
        for u in users:
            user_values.append({
                'name': u.name,
                'email': u.email,
                'cost_centre': u.cost_centre.code if u.cost_centre else None,
                'o365_licence': u.get_office_licence(),
                'active': u.active,
                'shared': u.shared_account,
            })
        resp = self.formatters.format(self.request, user_values)
        resp = {'objects': resp}
        return resp

    # Hack: duplicate list() method, decorated with skip_prepare in order to improve performance.
    @skip_prepare
    def list_fast(self):
        resp = cache.get(self.request.get_full_path())
        if resp:
            return resp
        FILTERS = {}
        # DepartmentUser object response.
        # Some of the request parameters below are mutually exclusive.
        if 'all' in self.request.GET:
            # Return all objects, including those deleted in AD.
            users = DepartmentUser.objects.all()
        elif 'email' in self.request.GET:
            # Always return an object by email.
            users = DepartmentUser.objects.filter(email__iexact=self.request.GET['email'])
        elif 'ad_guid' in self.request.GET:
            # Always return an object by UUID.
            users = DepartmentUser.objects.filter(ad_guid=self.request.GET['ad_guid'])
        elif 'cost_centre' in self.request.GET:
            # Always return all objects by cost centre (inc inactive & contractors).
            users = DepartmentUser.objects.filter(cost_centre__code__icontains=self.request.GET['cost_centre'])
        elif 'pk' in self.request.GET:
            # Return the sole user requested.
            users = DepartmentUser.objects.filter(pk=self.request.GET['pk'])
        else:
            # No other filtering:
            # Return 'active' DU objects, excluding predefined account types and contractors.
            FILTERS = DepartmentUser.ACTIVE_FILTER.copy()
            users = DepartmentUser.objects.filter(**FILTERS)
            users = users.exclude(account_type__in=DepartmentUser.ACCOUNT_TYPE_EXCLUDE)
        # Parameters to modify the API output.
        if 'minimal' in self.request.GET:
            # For the minimal response, we don't need a prefetch_related.
            self.VALUES_ARGS = self.MINIMAL_ARGS
        else:
            if 'compact' in self.request.GET:
                self.VALUES_ARGS = self.COMPACT_ARGS
            users = users.prefetch_related('manager', 'location', 'cost_centre')

        user_values = list(users.order_by('name').values(*self.VALUES_ARGS))
        resp = self.formatters.format(self.request, user_values)
        resp = {'objects': resp}
        # Cache the response for 300 seconds.
        cache.set(self.request.get_full_path(), resp, timeout=300)
        return resp

    def list(self):
        """Pass query params to modify the API output.
        """
        FILTERS = {}
        # Some of the request parameters below are mutually exclusive.
        if 'all' in self.request.GET:
            # Return all objects, including those deleted in AD.
            users = DepartmentUser.objects.all()
        elif 'email' in self.request.GET:
            # Always return an object by email.
            users = DepartmentUser.objects.filter(email__iexact=self.request.GET['email'])
        elif 'ad_guid' in self.request.GET:
            # Always return an object by UUID.
            users = DepartmentUser.objects.filter(ad_guid=self.request.GET['ad_guid'])
        elif 'cost_centre' in self.request.GET:
            # Always return all objects by cost centre (inc inactive & contractors).
            users = DepartmentUser.objects.filter(cost_centre__code__icontains=self.request.GET['cost_centre'])
        else:
            # No other filtering:
            # Return 'active' DU objects, excluding predefined account types and contractors.
            FILTERS = DepartmentUser.ACTIVE_FILTER.copy()
            users = DepartmentUser.objects.filter(**FILTERS)
            users = users.exclude(account_type__in=DepartmentUser.ACCOUNT_TYPE_EXCLUDE)

        # Parameters to modify the API output.
        if 'minimal' in self.request.GET:
            # For the minimal response, we don't need a prefetch_related.
            self.VALUES_ARGS = self.MINIMAL_ARGS
        else:
            if 'compact' in self.request.GET:
                self.VALUES_ARGS = self.COMPACT_ARGS
            users = users.prefetch_related('manager', 'location', 'cost_centre')

        user_values = list(users.order_by('name').values(*self.VALUES_ARGS))
        resp = self.formatters.format(self.request, user_values)
        return resp

    def detail(self, guid):
        """Detail view for a single DepartmentUser object.
        """
        resp = cache.get(self.request.get_full_path())
        if resp:
            return resp
        user = DepartmentUser.objects.filter(ad_guid=guid)
        if not user:
            user = DepartmentUser.objects.filter(email__iexact=guid.lower())
        user_values = list(user.values(*self.VALUES_ARGS))
        resp = self.formatters.format(self.request, user_values)[0]
        cache.set(self.request.get_full_path(), resp, timeout=300)
        return resp


class LocationResource(CSVDjangoResource):
    VALUES_ARGS = (
        'pk', 'name', 'address', 'phone', 'fax', 'email', 'point', 'url', 'bandwidth_url', 'active')

    def list_qs(self):
        FILTERS = {}
        if 'location_id' in self.request.GET:
            FILTERS['pk'] = self.request.GET['location_id']
        else:
            FILTERS['active'] = True
        return Location.objects.filter(**FILTERS).values(*self.VALUES_ARGS)

    @skip_prepare
    def list(self):
        data = list(self.list_qs())
        for row in data:
            if row['point']:
                row['point'] = row['point'].wkt
        return data


class UserSelectResource(DjangoResource):
    """A small API resource to provide DepartmentUsers for select lists.
    """
    preparer = FieldsPreparer(fields={
        'id': 'id',
        'text': 'email',
    })

    def list(self):
        FILTERS = DepartmentUser.ACTIVE_FILTER.copy()
        users = DepartmentUser.objects.filter(**FILTERS)
        if 'q' in self.request.GET:
            users = DepartmentUser.objects.filter(email__icontains=self.request.GET['q'])
        return users


@csrf_exempt
def profile(request):
    """An API view that returns the profile for the request user.
    """
    if not request.user.is_authenticated:
        return HttpResponseForbidden()

    # Profile API view should return one object only.
    self = DepartmentUserResource()
    if not hasattr(request, 'user') or not request.user.email:
        return HttpResponseBadRequest('No user email in request')
    qs = DepartmentUser.objects.filter(email__iexact=request.user.email)
    if qs.count() > 1 or qs.count() < 1:
        return HttpResponseBadRequest('API request for {} should return one profile; it returned {}!'.format(
            request.user.email, qs.count()))
    user = qs.get(email__iexact=request.user.email)

    if request.method == 'GET':
        data = qs.values(*self.VALUES_ARGS)[0]

    return HttpResponse(json.dumps(
        {'objects': [self.formatters.format(request, data)]}, cls=MoreTypesJSONEncoder),
        content_type='application/json')
