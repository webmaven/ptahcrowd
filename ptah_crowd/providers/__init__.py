import json
import logging
import sqlalchemy as sqla
from datetime import datetime, timedelta
from pyramid import security
from pyramid.view import view_config
from pyramid.config import Configurator
from pyramid.events import ApplicationCreated
from pyramid.threadlocal import get_current_registry
from pyramid.httpexceptions import HTTPFound

import ptah
import ptah_crowd
from ptah_crowd.schemas import lower

log = logging.getLogger('ptah_crowd')

TOKEN_TYPE = ptah.token.TokenType(
    '80c7492469d0497f974374af1b524dc0', timedelta(hours=8))


@ptah.subscriber(ApplicationCreated)
def settings_initialized(ev):
    registry = get_current_registry()

    cfg = ptah.get_settings(ptah_crowd.CFG_ID_AUTH, registry)
    providers = cfg['providers']
    if not providers:
        return

    config = Configurator(registry, autocommit=True)

    for provider in providers:
        log.info('Loaging "{0}" auth provider'.format(provider))
        config.include(
            'ptah_crowd.providers.{0}'.format(provider),
            route_prefix='/crowd-auth-provider')


@view_config(context='ptah_crowd.providers.AuthenticationComplete')
def auth_complete_view(context, request):
    entry = context.entry

    if entry.uri is None:
        # check verified emails
        if entry.verified:
            session = ptah.get_session()

            user = session.query(ptah_crowd.CrowdUser)\
                   .filter(ptah_crowd.CrowdUser.email == entry.email).first()
            if user is not None:
                entry.uri = user.__uri__
            else:
                # create user
                tinfo = ptah_crowd.get_user_type()

                user = tinfo.create(
                    title=entry.name,
                    login=entry.email,
                    email=entry.email,
                    password=entry.access_token)
                ptah_crowd.CrowdFactory().add(user)
                entry.uri = user.__uri__
        else:
            # verify email
            return HTTPFound(
                request.route_url(
                    'ptah-crowd-verify-email', subpath=(entry.uid,)))

        return login(entry.uri, request)


def login(uri, request):
    principal = ptah.resolve(uri)
    info = ptah.auth_service.authenticate_principal(principal)

    if info.status:
        request.registry.notify(
            ptah.events.LoggedInEvent(principal))

        location = '%s/login-success.html'%request.application_url

        headers = security.remember(request, principal.__uri__)
        return HTTPFound(headers = headers, location = location)

    if info.arguments.get('suspended'):
        return HTTPFound(
            location='%s/login-suspended.html'%request.application_url)

    ptah.add_message(request, info.message, 'warning')
    return HTTPFound(location = '%s/login.html'%request.application_url)


@view_config(
    route_name='ptah-crowd-verify-email',
    wrapper=ptah.wrap_layout('ptah-page'))
class VerifyEmail(ptah.form.Form):
    """ verify email """

    label = 'Please verify your email'

    fields = ptah.form.Fieldset(
        ptah.form.TextField(
            'email',
            title = 'E-mail',
            description = ('Please enter your email address.'
                           'Your email address will not be displayed to '
                           'any user or be shared with anyone else.'),
            preparer = lower,
            required = True,
            validator = ptah.form.Email())
        )

    def update(self):
        self.session = session = ptah.get_session()

        entry = session.query(Storage).filter(
            Storage.uid == self.request.subpath[0]).first()
        if entry is None:
            return HTTPFound(self.request.route_url('ptah-login'))

        self.entry = entry

        return super(VerifyEmail, self).update()

    @ptah.form.button('Verify', actype=ptah.form.AC_PRIMARY)
    def verify_handler(self):
        data, errors = self.extract()

        if errors:
            self.message(errors, 'form-error')
            return

        entry = self.entry
        request = self.request
        new_user = False
        email = data['email']

        user = self.session.query(ptah_crowd.CrowdUser).filter(
            ptah_crowd.CrowdUser.email == email).first()
        if user is None:
            new_user = True

            # create user
            tinfo = ptah_crowd.get_user_type()

            user = tinfo.create(
                title=entry.name,
                login=email,
                email=email,
                password=entry.access_token)
            ptah_crowd.CrowdFactory().add(user)

            uri = user.__uri__
            entry.uri = uri
            entry.email = email
        else:
            uri = user.__uri__

        data = {'uri': uri,
                'email': email,
                'uid': entry.uid}

        t = ptah.token.service.generate(TOKEN_TYPE, json.dumps(data))
        template = VerifyTemplate(entry, request, email=email, token=t)
        template.send()

        # login
        if new_user:
            self.message('Email verification email has been sent.')
            cfg = ptah.get_settings(ptah_crowd.CFG_ID_CROWD, request.registry)
            if cfg['validation']:
                if cfg['allow-unvalidated']:
                    entry.uri = uri
                    return login(uri, request)
            else:
                entry.uri = uri
                return login(uri, request)
        else:
            self.message('User with this email already exists. '
                         'You have to verify email before you can login.')

        return HTTPFound(location=request.application_url)


@view_config(route_name='ptah-crowd-verify-email-complete')
def verify(request):
    """Verify email"""
    t = request.subpath[0]

    data = ptah.token.service.get(t)
    if data is not None:
        data = json.loads(data)
        session = ptah.get_session()

        principal = ptah.resolve(data['uri'])
        entry = session.query(Storage).filter(Storage.uid==data['uid']).first()
        entry.uri = principal.__uri__
        entry.email = data['email']

        ptah.token.service.remove(t)
        ptah.add_message(request,"Email has been successfully verified.")

        headers = security.remember(request, principal.__uri__)
        return HTTPFound(location=request.application_url, headers=headers)

    ptah.add_message(request, "Can't verify email address.", 'warning')
    return HTTPFound(location=request.application_url)


class VerifyTemplate(ptah.mail.MailTemplate):

    subject = 'Verify Your Account'
    template = 'ptah_crowd:templates/verify_email.txt'

    def update(self):
        super(VerifyTemplate, self).update()

        self.url = self.request.route_url(
            'ptah-crowd-verify-email-complete', subpath=(self.token,))
        self.to_address = ptah.mail.formataddr((self.context.name, self.email))


#@view_config(context='velruse.exceptions.AuthenticationDenied')
def auth_denied_view(context, request):
    endpoint = request.registry.settings.get('velruse.endpoint')
    token = generate_token()
    storage = request.registry.velruse_store
    error_dict = {
        'code': context.code,
        'description': context.description,
    }
    storage.store(token, error_dict, expires=300)
    form = redirect_form(endpoint, token)
    return Response(body=form)


class AuthenticationComplete(object):
    """An AuthenticationComplete context object"""

    def __init__(self, entry):
        self.entry = entry
        self.uri = entry.uri


class Storage(ptah.get_base()):

    __tablename__ = 'ptah_crowd_auth_storage'

    access_token = sqla.Column(sqla.String(255), primary_key=True)
    domain = sqla.Column(sqla.String(255), default='')

    uri = sqla.Column(sqla.String(255), index=True)

    uid = sqla.Column(sqla.String(128), default='', unique=True)
    name = sqla.Column(sqla.String(255), default='')
    email = sqla.Column(sqla.String(128), default='')
    verified = sqla.Column(sqla.Boolean(), default=False)

    profile = sqla.Column(ptah.JsonDictType())
    expires = sqla.Column(sqla.DateTime())

    @classmethod
    def get_by_token(cls, access_token):
        return ptah.get_session().query(cls).filter(
            sqla.and_(cls.access_token == access_token)).first()

    @classmethod
    def create(cls, access_token, domain,
               uid='', name='', email='',
               verified=False, profile=None, expires=None):

        entry = cls(access_token=access_token,
                    domain=domain,
                    uid=uid,
                    name=name,
                    email=email.lower(),
                    verified=verified,
                    profile=profile)
        ptah.get_session().add(entry)
        return entry

    @classmethod
    def delete(cls, key):
        ptah.get_session().query(cls).filter(cls.key == key).delete()
        return True

    @classmethod
    def purge_expired(cls):
        ptah.get_session().query(cls)\
            .filter(cls.expires < datetime.utcnow()).delete()
        return True
