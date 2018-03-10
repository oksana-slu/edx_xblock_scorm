edx_xblock_scorm
=========================

XBlock to display SCORM content within the Open edX LMS.  Editable within Open edx Studio. Will save student state and report scores to the progress tab of the course.
Currently supports SCORM 1.2 standard, but not yet SCORM 2004.  It supports multi-SCO content packages.  


# Installation

## Using Ansible

* Add to your `server-vars.yml` file this entry underneath the `EDXAPP_EXTRA_REQUIREMENTS` key
    
```
    - name: 'git+https://github.com/appsembler/edx_xblock_scorm@use_ssla_player#egg=scormxblock'
```

* Configure a SCORM player backend in the XBlock settings, under the `"ScormXBlock"`.  Currently you must provide the SSLA player by JCA Solutions. 

```
EDXAPP_XBLOCK_SETTINGS:
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
    "SCORM_PKG_STORAGE_DIR": "scorms"
  }
```

Each backend is a key under `SCORM_PLAYER_BACKENDS` and should provide a `"name"` which will appear in the player dropdown in Studio, a `"location"` which is a path to the the player's default HTML page from the the web root, and optionally an additional key `"configuration"` storing JSON values which will override any JSON configuration keys used by the player (not yet fully implemented). Backend keys must not contain spaces or punctuation.

* Configure a SCORM package storage class. `"SCORM_FILE_STORAGE_TYPE"` should be set to `"django.core.files.storage.FileSystemStorage",` for now, since storage on S3 or otherwise at a different domain is not currently supported.  This will be addressed in late 2017.

* Configure a SCORM package storage directory.  This will be the directory name underneath the default `MEDIA_ROOT` as specified in your Django settings, or the directory used for external storage (e.g., Amazon S3.  S3 storage will require using CloudFront or another means to serve S3 assets from the same protocol, domain, subdomain,and port to get around cross-domain issues).

* Configure Staff Debug Info: If you want staff debug info for SCORM XBlocks to be visible to instructors and other permitted staff, add this key to your `EDXAPP_XBLOCK_SETTINGS` key for 'ScormXBlock'.  Only the 'Delete Student State' action will work; 'Reset Student Attempts' and 'Rescore Student Submission' are not yet operable, but may be in the future.

```    
"SCORM_DISPLAY_STAFF_DEBUG_INFO": true
```


# Server configuration

Nginx (or other front-end web server) must be configured to serve SCORM content. See the file [`docs/nginx_configuration.md`](docs/nginx_configuration.md) for edits that need to be made to your `/etc/nginx/sites-enabled/lms` and `/etc/nginx/sites-enabled/cms` files to serve your SCORM content.

# `Site` configuration

The SCORM XBlock is `Site`-aware.  Student views of XBlock instances will use the current `Site` domain as the LMS endpoint URL root.  Make sure your default any other `Site`s are configured with the proper domain.
A common mistake would be to leave the default `Site` domain as `"example.com"`.  Update your default `Site` domain via `/admin/sites/site`.

# Usage
* In Studio, add `scormxblock` to the list of advanced modules in the advanced settings of a course.
* Add a 'scorm' component to your Unit. 
* Specify a display name, an optional description, and choose a 'player' (IMPORTANT: currently only works using the commercial SSLA player from JCA Solutions.  Contact Appsembler if you would like assistance with this).  
* Specify a weight for your SCORM content within your Open edX course.  For example, your course SCO may have an internal max. score of 100.  If you give your SCORM component a weight of 10 and a student scores 50 within the SCORM course, they will receive 5 points within Open edX.  SCORM components can be weighted as normal against other gradable Open edX components.
* Choose a display format (popup or iframe -- only use iframe if your SCORM content package itself creates a popup window) and display size.   
* Upload a zip file containint your content package.  The `imsmanifest.xml` file must be at the root of the zipped package (i.e., make sure you don't have an additional directory at the root of the Zip archive which can handle if e.g., you select an entire folder and use Mac OS X's compress feature).
* Publish your content as usual.



