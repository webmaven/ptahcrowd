import transaction
import ptah
from ptah import config
from ptah.testing import PtahTestCase
from webob.multidict import MultiDict
from pyramid.testing import DummyRequest
from pyramid.view import render_view_to_response
from pyramid.httpexceptions import HTTPFound, HTTPForbidden

import ptahcrowd


class TestModule(PtahTestCase):

    _includes = ('ptahcrowd',)

    def test_manage_module(self):
        from ptah.manage.manage import PtahManageRoute
        from ptahcrowd.module import CrowdModule

        request = DummyRequest()

        ptah.auth_service.set_userid('test')

        cfg = ptah.get_settings(ptah.CFG_ID_PTAH)
        cfg['managers'] = ('*',)
        mr = PtahManageRoute(request)
        mod = mr['crowd']

        self.assertIsInstance(mod, CrowdModule)

    def test_manage_module_get(self):
        from ptahcrowd.module import CrowdModule
        from ptahcrowd.provider import CrowdUser

        user = CrowdUser(name='name', login='login', email='email')
        user.__type__.add(user)

        uri = user.__uri__

        mod = CrowdModule(None, DummyRequest())

        self.assertRaises(KeyError, mod.__getitem__, 'unkown')

        wu = mod[str(user.id)]

        self.assertIsInstance(wu, CrowdUser)
        self.assertEqual(wu.__uri__, uri)


class TestModuleView(PtahTestCase):

    _includes = ('ptahcrowd',)

    def _make_mod(self):
        from ptahcrowd.module import CrowdModule
        return CrowdModule(None, DummyRequest())

    def _make_user(self):
        from ptahcrowd.provider import CrowdUser

        user = CrowdUser(name='name', login='login', email='email')
        return user.__type__.add(user)

    def test_module_search(self):
        from ptahcrowd.views import CrowdModuleView

        mod = self._make_mod()

        form = CrowdModuleView(mod, DummyRequest(
                POST=MultiDict((('form.buttons.search', 'Search'),
                                ('term', 'search term')))))
        form.csrf = False
        res = form.update()

        self.assertIn('ptah-search-term', form.request.session)
        self.assertEqual(
            form.request.session['ptah-search-term'], 'search term')

    def test_module_clear(self):
        from ptahcrowd.views import CrowdModuleView

        mod = self._make_mod()

        form = CrowdModuleView(mod, DummyRequest(
                session = {'ptah-search-term': 'test'},
                POST=MultiDict((('form.buttons.clear', 'Clear'),))))
        form.csrf = False
        form.update()

        self.assertNotIn('ptah-search-term', form.request.session)

    def test_module_search_error(self):
        from ptahcrowd.views import CrowdModuleView

        mod = self._make_mod()

        form = CrowdModuleView(mod, DummyRequest(
                POST=MultiDict((('form.buttons.search', 'Search'),))))
        form.csrf = False
        form.update()

        self.assertIn('Please specify search term',
                      ptah.render_messages(form.request))

    def test_module_list(self):
        from ptahcrowd.views import CrowdModuleView

        mod = self._make_mod()
        user = self._make_user()

        request = DummyRequest(
            params = MultiDict(), POST = MultiDict())
        request.session['ptah-search-term'] = 'email'

        res = render_view_to_response(mod, request, '')

        self.assertIn('value="%s"'%user.id, res.text)

        res = render_view_to_response(
            mod,
            DummyRequest(params = MultiDict(), POST = MultiDict()), '')

        self.assertIn('value="%s"'%user.id, res.text)

        res = render_view_to_response(
            mod,
            DummyRequest(params = MultiDict({'batch': 1}),
                         POST = MultiDict()), '')

        self.assertIn('value="%s"'%user.id, res.text)

        res = render_view_to_response(
            mod,
            DummyRequest(params = MultiDict({'batch': 0}),
                         POST = MultiDict()), '')

        self.assertIn('value="%s"'%user.id, res.text)

    def test_module_validate(self):
        from ptahcrowd.provider import CrowdUser
        from ptahcrowd.views import CrowdModuleView

        mod = self._make_mod()
        user = self._make_user()
        user.validated = False

        id = user.id

        form = CrowdModuleView(mod, DummyRequest(
                POST=MultiDict((('uid', id),
                                ('validate', 'validate')))))

        form.csrf = False
        form.update()
        transaction.commit()

        self.assertIn('The selected accounts have been validated.',
                      ptah.render_messages(form.request))

        user = ptah.get_session().query(CrowdUser)\
            .filter(CrowdUser.id==id).first()
        self.assertTrue(user.validated)

    def test_module_suspend(self):
        from ptahcrowd.provider import CrowdUser
        from ptahcrowd.views import CrowdModuleView

        mod = self._make_mod()
        user = self._make_user()
        user.suspended = False
        id = user.id

        form = CrowdModuleView(mod, DummyRequest(
                POST=MultiDict((('uid', id),
                                ('suspend', 'suspend')))))
        form.request.POST[form.csrfname] = form.request.session.get_csrf_token()
        form.update()

        self.assertIn('The selected accounts have been suspended.',
                      ptah.render_messages(form.request))
        transaction.commit()

        user = ptah.get_session().query(CrowdUser)\
            .filter(CrowdUser.id==id).first()
        self.assertTrue(user.suspended)

    def test_module_activate(self):
        from ptahcrowd.provider import CrowdUser
        from ptahcrowd.views import CrowdModuleView

        mod = self._make_mod()
        user = self._make_user()
        user.suspended = True

        id = user.id

        form = CrowdModuleView(mod, DummyRequest(
                POST=MultiDict((('uid', user.id),
                                ('activate', 'activate')))))

        form.csrf = False
        form.update()
        transaction.commit()

        self.assertIn('The selected accounts have been activated.',
                      ptah.render_messages(form.request))
        user = ptah.get_session().query(CrowdUser)\
            .filter(CrowdUser.id==id).first()
        self.assertFalse(user.suspended)

    def test_module_remove(self):
        from ptahcrowd.views import CrowdModuleView

        mod = self._make_mod()
        user = self._make_user()
        user.suspended = False

        uri = user.__uri__

        form = CrowdModuleView(mod, DummyRequest(
                POST=MultiDict((('uid', user.id),
                                ('remove', 'remove')))))
        form.update()

        self.assertIn('The selected accounts have been removed.',
                      ptah.render_messages(form.request))
        transaction.commit()

        user = ptah.resolve(uri)
        self.assertIsNone(user)
