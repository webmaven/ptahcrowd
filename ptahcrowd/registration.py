""" user registration form """
from pyramid import security
from pyramid.view import view_config
from pyramid.httpexceptions import HTTPFound, HTTPForbidden

import ptah
from ptah import config, form
from ptah.password import PasswordSchema
from ptah.events import PrincipalRegisteredEvent

from ptahcrowd.provider import get_user_type
from ptahcrowd.settings import _, CFG_ID_CROWD
from ptahcrowd.schemas import RegistrationSchema
from ptahcrowd.validation import initiate_email_validation


@view_config(
    route_name='ptah-join',
    wrapper=ptah.wrap_layout('ptah-page'))

class Registration(form.Form):
    """ Ptah crowd registration form """

    label = _("Registration")
    fields = form.Fieldset(RegistrationSchema, PasswordSchema)
    autocomplete = 'off'

    def update(self):
        uri = ptah.auth_service.get_userid()
        if uri is not None:
            return HTTPFound(location = self.request.application_url)

        self.cfg = ptah.get_settings(CFG_ID_CROWD, self.request.registry)
        if not self.cfg['join'] or not self.cfg['type']:
            return HTTPForbidden('Site registraion is disabled.')

        return super(Registration, self).update()

    def create(self, data):
        tinfo = get_user_type(self.request.registry)

        # create user
        user = tinfo.create(
            name=data['name'], login=data['login'], email=data['login'])

        # set password
        user.password = ptah.pwd_tool.encode(data['password'])

        return tinfo.add(user)

    @form.button(_("Register"), actype=form.AC_PRIMARY)
    def register_handler(self):
        data, errors = self.extract()
        if errors:
            self.message(errors, 'form-error')
            return

        user = self.create(data)
        self.request.registry.notify(PrincipalRegisteredEvent(user))

        # validation
        if self.cfg['validation']:
            initiate_email_validation(user.email, user, self.request)
            self.message('Validation email has been sent.')
            if not self.cfg['allow-unvalidated']:
                return HTTPFound(location=self.request.application_url)

        # authenticate
        info = ptah.auth_service.authenticate(
            {'login': user.login, 'password': user.password})
        if info.status:
            headers = security.remember(self.request, info.__uri__)
            return HTTPFound(
                location='%s/login-success.html'%self.request.application_url,
                headers = headers)
        else:
            self.message(info.message) # pragma: no cover
