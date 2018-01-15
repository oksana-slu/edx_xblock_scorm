# Change Log

Notable changes to this project will be documented in this file, though
the change log was not started until later in the project.

The format is based on [Keep a Changelog](http://keepachangelog.com/).

## [Unreleased]

## [0.4.0] - 2018-01-15

### Added

- Add a `REVERSE_STUDENT_NAMES` XBlock setting defaulting to True.  
Normally SCORM API wants "family name given name" order, but some content packages 
may want first last order. "Reversed" is from the North American perspective
but maybe normal order in other contexts.  Sorry :)
- AUTHORS file and this CHANGELOG

### Fixed

- Fix charset declaration for new style WebOb.Response.
- Set size of iframe window for iframe mode.
- Update scoring to work better with SCORM 2004.

### Changed

- Use `Site` and `SiteConfiguration` to find LMS base for Request context,
not microsite configuration.
