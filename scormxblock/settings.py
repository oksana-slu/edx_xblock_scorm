"""
Site-aware SCORM XBlock mixin
"""
import logging

from xblock.core import XBlock

try:
    from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers
    has_siteconfiguration = True
except ImportError:
    has_siteconfiguration = False


logger = logging.getLogger(__name__)


class ConfigurationSettingsMixin(XBlock):
    """
    SettingsMixin providing SiteConfiguration-based overrides and default settings
    via SettingsService

    Sample default settings in /edx/app/edxapp/(lms|cms).env.json:
    "XBLOCK_SETTINGS": {
        "ScormXBlock": {
            "SCORM_PLAYER_LOCAL_STORAGE_ROOT": "scormplayers",
            "SCORM_PLAYER_BACKENDS": {
              "ssla": {
                "name": "SSLA",
                "location": "/static/scorm/ssla/player.htm",
                "repo": "git@github.com:appsembler/ssla-scorm-player.git",
                "version": "nyif/master",
                "configuration": {}
              }
            },
            "SCORM_FILE_STORAGE_TYPE": "django.core.files.storage.FileSystemStorage",
            "SCORM_PKG_STORAGE_DIR": "scorms",
            "SCORM_DISPLAY_STAFF_DEBUG_INFO": true,
            "SCORM_REVERSE_STUDENT_NAMES": true,
            "SCORM_USE_PACKAGE_VERSIONING": false
        }
    }

    Keys can be overridden per-Site(/domain) if defined in SiteConfiguration object for Django Site;
    e.g., in a SiteConfiguration, a JSON object matching this structure:

    { 
        "XBLOCK_SETTINGS": {
            "ScormXBlock": {
                "SCORM_REVERSE_STUDENT_NAMES": false,
                "SCORM_FILE_STORAGE_TYPE": "storages.backends.s3boto.S3BotoStorage",
                "SCORM_PKG_STORAGE_DIR": "micrositeX",
                "SCORM_USE_PACKAGE_VERSIONING": true
            }
        }
    }

    Only the keys present in SiteConfiguration will override platform-wide values.
    Settings will be retrieved in this order: 
    1) retrieved from XBLOCK_SETTINGS in base Django settings object for the context (LMS/CMS); 
    2) updated by any overrides from a match by domain to a SiteConfiguration
    3) updated by any overrides from a match by course org of XBlock instance parent Course, 
    via SiteConfiguration.get_value_by_org.

    To make sure Site-specific settings apply to authoring and studio views in Studio, the 
    parent course of the XBlock instance should belong to an org matching a `course_org_filter` 
    value in a SiteConfiguration.  Domain matches, or
    "2)" above will usually not provide configuration in the Studio context.  Creating a separate
    SiteConfiguration for the Studio domain is discouraged, as it can lead to mismatched configuration
    between the LMS and Studio, and possible errors.  If `course_org_filter` cannot be used as
    a single differentiator between Sites deploying the XBlock, makes sure that configuration 
    will be the same for the Site between LMS and Studio.

    """
    @property
    def settings(self):
        """
        Return xblock settings for platform/domain/course org

        Returned value depends on the context:
        - `studio_view` or `author_view` executed in CMS will get settings from `cms.env.json`.
        - `student_view` executed in LMS will get settings from `lms.env.json`.
        Either context will also get settings overrides from domain/course org match to a SiteConfiguration

        Returns:
            dict: Settings from configuration. E.g.
            {
                "SCORM_FILE_STORAGE_TYPE": "django.core.files.storage.FileSystemStorage",
                "SCORM_PKG_STORAGE_DIR": "scorms",                
                ...
            }
        """
        # in Studio at least can't seem to get any value from xmodule settings service
        # so using direct import approach
        from django.conf import settings as dj_settings
        if not hasattr(dj_settings, 'XBLOCK_SETTINGS'):
            base_settings = {}
        else:
            base_settings = dj_settings.XBLOCK_SETTINGS.get("ScormXBlock", {})
        if has_siteconfiguration:
            site_settings_by_domain = configuration_helpers.get_value("XBLOCK_SETTINGS", {}).get("ScormXBlock", {})
            base_settings.update(site_settings_by_domain)
            if self.course_org:
                site_settings_by_org = configuration_helpers.get_value_for_org(self.course_org, "XBLOCK_SETTINGS", {}).get("ScormXBlock")
                base_settings.update(site_settings_by_org)
            return base_settings
        else:
            return base_settings

    @property
    def course_org(self):
        return self.runtime.course_id.org
