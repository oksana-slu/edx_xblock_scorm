import importlib
import json
import os
import pkg_resources
import zipfile
import shutil
import tempfile
import logging
import encodings

from django.conf import settings
from django.utils import encoding
from webob import Response

from xblock.core import XBlock, UNSET
from xblock.fields import Scope, String, Integer, Boolean, Float
from xblock.fragment import Fragment

from openedx.core.lib.xblock_utils import add_staff_markup
try:
    from openedx.core.djangoapps.theming.helpers import get_current_site
except ImportError:
    from django.contrib.sites.shortcuts import get_current_site
    from request_cache.middleware import RequestCache

from mako.template import Template as MakoTemplate

import settings as settings_mixin


# Make '_' a no-op so we can scrape strings
_ = lambda text: text

logger = logging.getLogger(__name__)


DEFAULT_STORAGE_TYPE = "django.core.files.storage.default_storage"
SCORM_PKG_INTERNAL = {"value": "SCORM_PKG_INTERNAL", "display_name": "Internal Player: index.html in SCORM package"}
DEFAULT_SCO_MAX_SCORE = 100
DEFAULT_IFRAME_WIDTH = 800
DEFAULT_IFRAME_HEIGHT = 400
SCORM_COMPLETE_STATUSES = (u'completed', u'passed', u'failed')

AVAIL_ENCODINGS = encodings.aliases.aliases
DEFAULT_SITE_DOMAIN = "example.com"


class ScormXBlock(settings_mixin.ConfigurationSettingsMixin, XBlock):

    has_score = True
    has_author_view = True

    display_name = String(
        display_name=_("Display Name"),
        help=_("Display name for this module"),
        default="SCORM",
        scope=Scope.settings
    )
    description = String(
        display_name=_("Description"),
        help=_("Brief description of the SCORM modules will be displayed above the player. Can contain HTML."),
        default="",
        scope=Scope.settings
    )
    scorm_file = String(
        display_name=_("Upload scorm file (.zip)"),
        help=_('Upload a new SCORM package.'),
        scope=Scope.settings
    )
    scorm_player = String(
        values=[SCORM_PKG_INTERNAL, ], # defer addition of other possible values until XBlock instantiation
        # [{"value": key, "display_name": defined_players[key]['name']} for key in defined_players.keys()] + [SCORM_PKG_INTERNAL, ],
        display_name=_("SCORM player"),
        help=_("SCORM player configured in Django settings, or index.html file contained in SCORM package"),
        scope=Scope.settings
    )
    # this stores latest raw SCORM API data in JSON string
    raw_scorm_status = String(
        scope=Scope.user_state,
        default='{}'
    )
    scorm_initialized = Boolean(
        scope=Scope.user_state,
        default=False
    )
    lesson_status = String(
        scope=Scope.user_state,
        default='not attempted'
    )
    lesson_score = Float(
        scope=Scope.user_state,
        default=0
    )
    weight = Integer(
        default=1,
        help=_('SCORM block\'s problem weight in the course, in points.  If not graded, set to 0'),
        scope=Scope.settings
    )
    display_type = String(
        display_name =_("Display Type"),
        values=["iframe", "popup"],
        default="iframe",
        help=_("Open in a new popup window, or an iframe.  This setting may be overridden by player-specific configuration."),
        scope=Scope.settings
    )
    display_width = Integer(
        display_name =_("Display Width (px)"),
        help=_('Width of iframe or popup window'),
        default=820,
        scope=Scope.settings
    )
    display_height = Integer(
        display_name =_("Display Height (px)"),
        help=_('Height of iframe or popup window'),
        default=450,
        scope=Scope.settings
    )
    encoding = String(
        display_name=_("SCORM Package text encoding"),
        default='cp850',
        help=_("Character set used in SCORM package.  Defaults to cp850 (or IBM850), for Latin-1: Western European languages)"),
        values=[{"value": AVAIL_ENCODINGS[key], "display_name": key} for key in sorted(AVAIL_ENCODINGS.keys())],
        scope=Scope.settings
    )
    player_configuration = String(
        display_name =_("Player Configuration"),
        default='',
        help=_("JSON object string with overrides to be passed to selected SCORM player.  These will be exposed as data attributes on the host iframe and sent in a window.postMessage to the iframe's content window. Attributes can be any.  'Internal player' will always check this field for an 'initial_html' attribute to override index.html as the initial page."),
        scope=Scope.settings
    )

    @property
    def scorm_players(self):
        return self.settings.get("SCORM_PLAYER_BACKENDS", [])

    @property
    def scorm_storage_dir(self):
        return self.settings.get("SCORM_PKG_STORAGE_DIR", "scorms")

    @property
    def scorm_storage(self):
        scorm_file_storage_type = self.settings.get("SCORM_FILE_STORAGE_TYPE", DEFAULT_STORAGE_TYPE)
        mod, store_class = scorm_file_storage_type.rsplit('.', 1)
        scorm_storage_module = importlib.import_module(mod)
        scorm_storage_class = getattr(scorm_storage_module, store_class)
        if scorm_file_storage_type.endswith('default_storage'):
            scorm_storage_instance = scorm_storage_class
        else:
            scorm_storage_instance = scorm_storage_class()
        return scorm_storage_instance

    @property
    def reverse_student_names(self):
        return self.settings.get("SCORM_REVERSE_STUDENT_NAMES", True)

    #TODO: remove this as an option. Always have it True
    @property
    def scorm_display_staff_debug_info(self):
        return self.settings.get("SCORM_DISPLAY_STAFF_DEBUG_INFO", False)

    @property
    def student_id(self):
        if hasattr(self, "scope_ids"):
            return self.scope_ids.user_id
        else:
            return None

    @property
    def student_name(self):
        anon_id = self.runtime.anonymous_student_id
        student = self.runtime.get_real_user(anon_id) if self.runtime.get_real_user is not None else None
        if student:
            try:
                # reverse should be default and is expected by SCORM API 
                # but can be overridden via XBLOCK settings
                reverse = self.reverse_student_names
                split_name = student.profile.name.split(' ')
                first_name = student.first_name if student.first_name else split_name[0]
                last_name = student.last_name if student.last_name else ' '.join(split_name[1:])
                if reverse:
                    return u"{}, {}".format(last_name, first_name)
                else:
                    return u"{} {}".format(first_name, last_name)
            except (AttributeError, IndexError):
                return u""
        else:
            return u""

    @property
    def course_id(self):
        return self.runtime.course_id

    def __init__(self, runtime, field_data=None, scope_ids=UNSET, *args, **kwargs):
        # update any field value options from configuration
        super(ScormXBlock, self).__init__(runtime=runtime, scope_ids=scope_ids, field_data=field_data, *args, **kwargs)
        defined_players = self.scorm_players
        self.fields['scorm_player']._values = [{"value": key, "display_name": defined_players[key]['name']} for key in defined_players.keys()] + [SCORM_PKG_INTERNAL,]

    def _serialize_opaque_key(self, key):
        if hasattr(key, 'to_deprecated_string'):
            return key.to_deprecated_string()
        else:
            return unicode(key)        

    def resource_string(self, path):
        """Handy helper for getting resources from our kit."""
        data = pkg_resources.resource_string(__name__, path)
        return data.decode("utf8")

    def student_view(self, context=None, authoring=False):
        scheme = 'https' if settings.HTTPS == 'on' else 'http'
        
        try:
            site = get_current_site()  # theming.helpers
        except TypeError:
            site = get_current_site(RequestCache.get_current_request())  # django.contrib.site
        try:  
            # guard against unset/default Site domain           
            lms_base = site.domain if str(site.domain) != DEFAULT_SITE_DOMAIN else settings.ENV_TOKENS.get("LMS_BASE")
        except AttributeError:
            lms_base = settings.ENV_TOKENS("LMS_BASE")    

        scorm_player_url = ""

        if self.scorm_player == 'SCORM_PKG_INTERNAL':
            # TODO: support initial filename other than index.html for internal players
            scorm_player_url = '{}://{}{}'.format(scheme, lms_base, self.scorm_file)
        elif self.scorm_player:
            # SSLA: launch.htm?courseId=1&studentName=Caudill,Brian&studentId=1&courseDirectory=courses/SSLA_tryout
            player_config = self.scorm_players[self.scorm_player]
            player  = player_config['location']
            if '://' in player:
                scorm_player_url = player
            else:    
                scorm_player_url = '{}://{}{}'.format(scheme, lms_base, player)
                    
        html = self.resource_string("static/html/scormxblock.html")

        # don't call handlers if student_view is not called from within LMS
        # (not really a student)
        if not authoring:
            get_url = '{}://{}{}'.format(scheme, lms_base, self.runtime.handler_url(self, "get_raw_scorm_status"))
            set_url = '{}://{}{}'.format(scheme, lms_base, self.runtime.handler_url(self, "set_raw_scorm_status"))
        # PreviewModuleSystem (runtime Mixin from Studio) won't have a hostname            
        else:
            # we don't want to get/set SCORM status from preview
            get_url = set_url = '#'

        # if display type is popup, don't use the full window width for the host iframe
        iframe_width = self.display_type=='popup' and DEFAULT_IFRAME_WIDTH or self.display_width;
        iframe_height = self.display_type=='popup' and DEFAULT_IFRAME_HEIGHT or self.display_height;

        try:
            player_config = json.loads(self.player_configuration)
        except ValueError:
            player_config = {}

        frag = Fragment()
        frag.add_content(MakoTemplate(text=html.format(self=self, scorm_player_url=scorm_player_url,
                                                       get_url=get_url, set_url=set_url, 
                                                       iframe_width=iframe_width, iframe_height=iframe_height,
                                                       player_config=player_config, 
                                                       scorm_file=self.scorm_file)
                                     ).render_unicode())

        frag.add_css(self.resource_string("static/css/scormxblock.css"))
        context['block_id'] = self.url_name
        js = self.resource_string("static/js/src/scormxblock.js")
        jsfrag = MakoTemplate(js).render_unicode(**context)
        frag.add_javascript(jsfrag)


        # TODO: this will only work to display staff debug info if 'scormxblock' is one of the
        # categories of blocks that are specified in lms/templates/staff_problem_info.html so this will
        # for now have to be overridden in theme or directly in edx-platform
        # TODO: is there another way to approach this?  key's location.category isn't mutable to spoof 'problem',
        # like setting the name in the entry point to 'problem'.  Doesn't seem like a good idea.  Better to 
        # have 'staff debuggable' categories configurable in settings or have an XBlock declare itself staff debuggable
        if self.scorm_display_staff_debug_info and not authoring:  # don't show for author preview
            from courseware.access import has_access
            from courseware.courses import get_course_by_id

            course = get_course_by_id(self.xmodule_runtime.course_id)
            dj_user = self.xmodule_runtime._services['user']._django_user
            has_instructor_access = bool(has_access(dj_user, 'instructor', course))
            if has_instructor_access:
                disable_staff_debug_info = settings.FEATURES.get('DISPLAY_DEBUG_INFO_TO_STAFF', True) and False or True
                block = self
                view = 'student_view'
                frag = add_staff_markup(dj_user, has_instructor_access, disable_staff_debug_info, block, view, frag, context)

        frag.initialize_js('ScormXBlock_{0}'.format(context['block_id']))
        return frag

    def author_view(self, context=None):
        return self.student_view(context, authoring=True)

    def studio_view(self, context=None):
        html = self.resource_string("static/html/studio.html")
        frag = Fragment()
        context = {'block': self}
        frag.add_content(MakoTemplate(text=html).render_unicode(**context))
        frag.add_css(self.resource_string("static/css/scormxblock.css"))
        frag.add_javascript(self.resource_string("static/js/src/studio.js"))
        frag.initialize_js('ScormStudioXBlock')
        return frag

    @XBlock.handler
    def studio_submit(self, request, suffix=''):
        self.display_name = request.params['display_name']
        self.description = request.params['description']
        self.weight = request.params['weight']
        self.display_width = request.params['display_width']
        self.display_height = request.params['display_height']
        self.display_type = request.params['display_type']
        self.scorm_player = request.params['scorm_player']
        self.encoding = request.params['encoding']

        if request.params['player_configuration']:
            try:
                json.loads(request.params['player_configuration'])  # just validation
                self.player_configuration = request.params['player_configuration']
            except ValueError, e:
                return Response(json.dumps({'result': 'failure', 'error': 'Invalid JSON in Player Configuration'.format(e)}), content_type='application/json', charset='UTF-8')

        # scorm_file should only point to the path where imsmanifest.xml is located
        # scorm_player will have the index.html, launch.htm, etc. location for the JS player
        # TODO: the below could fail after deleting all of the contents from the storage. to handle
        if hasattr(request.params['file'], 'file'):
            file = request.params['file'].file
            zip_file = zipfile.ZipFile(file, 'r')
            storage = self.scorm_storage
            
            path_to_file = os.path.join(self.scorm_storage_dir, self.location.block_id)

            if storage.exists(os.path.join(path_to_file, 'imsmanifest.xml')):
                try:
                    shutil.rmtree(os.path.join(storage.location, path_to_file))
                except OSError:
                    # TODO: for now we are going to assume this means it's stored on S3 if not local
                    try:
                        for key in storage.bucket.list(prefix=path_to_file):
                            key.delete()
                    except AttributeError:
                        return Response(json.dumps({'result': 'failure', 'error': 'Unsupported storage. Unable to overwrite old SCORM package contents'}), content_type='application/json', charset='UTF-8')

            tempdir = tempfile.mkdtemp()
            zip_file.extractall(tempdir)

            to_store = []
            for (dirpath, dirnames, files) in os.walk(tempdir):
                for f in files:
                    to_store.append(os.path.join(os.path.abspath(dirpath), f))

            # TODO: look at optimization of file handling, save

            for f in to_store:
                # defensive decode/encode from zip
                f_path = f.decode(self.encoding).encode('utf-8').replace(tempdir, '')
                with open(f, 'rb+') as fh:
                    try:
                        storage.save('{}{}'.format(path_to_file, f_path), fh)
                    except encoding.DjangoUnicodeDecodeError, e:
                        logger.warn('SCORM XBlock Couldn\'t store file {} to storage. {}'.format(f, e))

            shutil.rmtree(tempdir)

            # strip querystrings
            url = storage.url(path_to_file)
            self.scorm_file = '?' in url and url[:url.find('?')] or url

        return Response(json.dumps({'result': 'success'}), content_type='application/json', charset='UTF-8')

    # if player sends SCORM API JSON directly
    @XBlock.json_handler
    def scorm_get_value(self, data, suffix=''):
        name = data.get('name')
        if name == 'cmi.core.lesson_status':
            return {'value': self.lesson_status}
        return {'value': ''}

    # if player sends SCORM API JSON directly
    @XBlock.json_handler
    def scorm_set_value(self, data, suffix=''):
        context = {'result': 'success'}
        name = data.get('name')
        if name == 'cmi.core.lesson_status' and data.get('value') != 'completed':
            self.lesson_status = data.get('value')
            self._publish_grade()
            context.update({"lesson_score": self.lesson_score})
        if name == 'cmi.core.score.raw':
            self._set_lesson_score(data.get('value',0))
        return context

    def _get_all_scos(self):
        return json.loads(self.raw_scorm_status).get('scos', None)

    def _status_serialize_key(self, key, val):
        """
        update value in JSON serialized raw_scorm_status
        passing a string key and a deserialized object
        """
        status = json.loads(self.raw_scorm_status)
        status[key] = val
        self.raw_scorm_status = json.dumps(status)

    def _scos_set_values(self, key, val, overwrite=False):
        """
        set a value for a key on all scos
        return new full raw scorm data
        """
        scos = self._get_all_scos()
        if scos:
            for sco in scos:
                if not scos[sco].get('key') or (scos[sco].get('key') and overwrite):
                    scos[sco][key] = val
            self._status_serialize_key('scos', scos)

    def _init_scos(self):
        """
        initialize all SCOs with proper credit and status values in case 
        content package does not do this correctly
        """
        
        # set all scos lesson status to 'not attempted'
        # set credit/no-credit on all scos
        credit = self.weight > 0 and 'credit' or 'no-credit'
        self._scos_set_values('cmi.core.credit', credit)
        self._scos_set_values('cmi.core.lesson_status', 'not attempted', True)
        self.scorm_initialized = True

    @XBlock.handler
    def get_raw_scorm_status(self, request, suffix=''):
        """ 
        retrieve JSON SCORM API status as stored by SSLA player (or potentially others)
        """
        # TODO: handle errors
        # TODO: this is specific to SSLA player at this point.  evaluate for broader use case
        return Response(self.raw_scorm_status, content_type='application/json', charset='UTF-8')

    @XBlock.handler
    def set_raw_scorm_status(self, request, suffix=''):
        """
        store JSON SCORM API status from SSLA player (or potentially others)
        """
        # TODO: this is specific to SSLA player at this point.  evaluate for broader use case
        data = request.POST['data']
        scorm_data = json.loads(data)

        new_status = scorm_data.get('status', 'not attempted')

        if not self.scorm_initialized:
            self._init_scos()

        self.raw_scorm_status = data
                
        self.lesson_status = new_status

        score = scorm_data.get('score')
        self._publish_grade(new_status, score)
        self.save()

        # TODO: handle errors
        return Response(json.dumps(self.raw_scorm_status), content_type='application/json', charset='UTF-8')

    def _get_value_from_sco(self, sco, key, default):
        """
        return a set or default value from a key in a SCO
        treat blank string values as empty
        """
        try:
            val = sco[key]
        except (KeyError, ValueError):
            return default
        finally:
            if str(val) == '':
                return default
            else:
                return val

    def _set_lesson_score(self, scos):
        """
        roll up a total lesson score from an average of SCO scores
        """
        # note SCORM 2004+ supports complex weighting of scores from multiple SCOs
        # see http://scorm.com/blog/2009/10/score-rollup-in-scorm-1-2-theres-no-silver-bullet/
        # For now we will weight each SCO equally and take an average
        # TODO: handle more complex weighting when we support SCORM2004+
        total_score = 0
        for sco in scos.keys():
            sco = scos[sco]['data']
            total_score += int(self._get_value_from_sco(sco, 'cmi.core.score.raw', 0))
        score_rollup = float(total_score) / float(len(scos.keys()))
        self.lesson_score = score_rollup
        return score_rollup


    def _publish_grade(self, status, score):
        """
        publish the grade in the LMS.
        """
        
        # We must do this regardless of the lesson
        # status to avoid race condition issues where a grade of None might overwrite a 
        # grade value for incomplete lesson statuses.
        
        # translate the internal score as a percentage of block's weight
        # we are assuming here the best practice for SCORM 1.2 of a max score of 100
        # if we weren't dealing with KESDEE publisher's incorrect usage of cmi.core.score.max
        # we could compute based on a real max score
        # in practice, SCOs will almost certainly have a max of 100
        # http://www.ostyn.com/blog/2006/09/scoring-in-scorm.html
        # TODO: handle variable max scores when we support SCORM2004+ or a better KESDEE workaround
        if score != '':
            self.runtime.publish(
                self,
                'grade',
                {
                    'value': (float(score)/float(DEFAULT_SCO_MAX_SCORE)) * self.weight,
                    'max_value': self.weight,
                })

    @staticmethod
    def workbench_scenarios():
        """A canned scenario for display in the workbench."""
        return [
            ("ScormXBlock",
             """<vertical_demo>
                <scormxblock/>
                </vertical_demo>
             """),
        ]
