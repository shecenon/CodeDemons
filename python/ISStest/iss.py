"""Inno Setup Script Parser.

A setup file consists of sections, lead by a "[section]" header,
and followed by "name: value" entries or list, with continuations and such in
the style of RFC 822.

Intrinsic defaults can be specified by passing them into the
ConfigParser constructor as a dictionary.

class:

ConfigParser -- responsible for parsing a list of
                configuration files, and managing the parsed database.

    methods:

    __init__(defaults=None)
        create the parser and specify a dictionary of intrinsic defaults.  The
        keys must be strings, the values must be appropriate for %()s string
        interpolation.  Note that `__name__' is always an intrinsic default;
        its value is the section's name.

    sections()
        return all the configuration section names, sans DEFAULT

    has_section(section)
        return whether the given section exists

    has_option(section, option)
        return whether the given option exists in the given section

    options(section)
        return list of configuration options for the named section

    read(filenames)
        read and parse the list of named configuration files, given by
        name.  A single filename is also allowed.  Non-existing files
        are ignored.  Return list of successfully read files.

    get(section, option, raw=False, vars=None)
        return a string value for the named option.  All % interpolations are
        expanded in the return values, based on the defaults passed into the
        constructor and the DEFAULT section.  Additional substitutions may be
        provided using the `vars' argument, which must be a dictionary whose
        contents override any pre-existing defaults.


    items(section, raw=False, vars=None)
        return a list of tuples with (name, value) for each option
        in the section.

    remove_section(section)
        remove the given file section and all its options

    remove_option(section, option)
        remove the given option from the given section

    set(section, option, value)
        set the given option

    write(fp)
        write the configuration state in .ini format
"""

try:
    from collections import OrderedDict as _default_dict
except ImportError:
    # fallback for setup.py which hasn't yet built _collections
    _default_dict = dict

import re

__all__ = ["NoSectionError", "DuplicateSectionError", "NoOptionError",
            "ParsingError", "MissingSectionHeaderError",
           "ISSParser", "DEFAULTSECT", "SETUP", "CONTENTBLOCK"]

DEFAULTSECT = "DEFAULT" 
SETUP = 'Setup'
CONTENTBLOCK = '__Content__'

# exception classes
class Error(Exception):
    """Base class for ConfigParser exceptions."""

    def _get_message(self):
        """Getter for 'message'; needed only to override deprecation in
        BaseException."""
        return self.__message

    def _set_message(self, value):
        """Setter for 'message'; needed only to override deprecation in
        BaseException."""
        self.__message = value

    # BaseException.message has been deprecated since Python 2.6.  To prevent
    # DeprecationWarning from popping up over this pre-existing attribute, use
    # a new property that takes lookup precedence.
    message = property(_get_message, _set_message)

    def __init__(self, msg=''):
        self.message = msg
        Exception.__init__(self, msg)

    def __repr__(self):
        return self.message

    __str__ = __repr__

class NoSectionError(Error):
    """Raised when no section matches a requested option."""

    def __init__(self, section):
        Error.__init__(self, 'No section: %r' % (section,))
        self.section = section
        self.args = (section, )

class DuplicateSectionError(Error):
    """Raised when a section is multiply-created."""

    def __init__(self, section):
        Error.__init__(self, "Section %r already exists" % section)
        self.section = section
        self.args = (section, )

class NoOptionError(Error):
    """A requested option was not found."""

    def __init__(self, option, section):
        Error.__init__(self, "No option %r in section: %r" %
                       (option, section))
        self.option = option
        self.section = section
        self.args = (option, section)

class ParsingError(Error):
    """Raised when a configuration file does not follow legal syntax."""

    def __init__(self, filename):
        Error.__init__(self, 'File contains parsing errors: %s' % filename)
        self.filename = filename
        self.errors = []
        self.args = (filename, )

    def append(self, lineno, line):
        self.errors.append((lineno, line))
        self.message += '\n\t[line %2d]: %s' % (lineno, line)

class MissingSectionHeaderError(ParsingError):
    """Raised when a key-value pair is found before any section header."""

    def __init__(self, filename, lineno, line):
        Error.__init__(
            self,
            'File contains no section headers.\nfile: %s, line: %d\n%r' %
            (filename, lineno, line))
        self.filename = filename
        self.lineno = lineno
        self.line = line
        self.args = (filename, lineno, line)

class ConfigParser:
    def __init__(self, defaults=None, dict_type=_default_dict,
                 allow_no_value=False):
        self._dict = dict_type
        self._sections = self._dict()
        self._defaults = self._dict()
        if allow_no_value:
            self._optcre = self.OPTCRE_NV
        else:
            self._optcre = self.OPTCRE
        if defaults:
            for key, value in defaults.items():
                self._defaults[key] = value

    def defaults(self):
        return self._defaults

    def sections(self):
        """Return a list of section names, excluding [DEFAULT]"""
        # self._sections will never have [DEFAULT] in it
        return self._sections.keys()

    def add_section(self, section):
        """Create a new section in the configuration.

        Raise DuplicateSectionError if a section by the specified name
        already exists. Raise ValueError if name is DEFAULT or any of it's
        case-insensitive variants.
        """
        if section.lower() == "default":
            raise ValueError, 'Invalid section name: %s' % section

        if section in self._sections:
            raise DuplicateSectionError(section)
        self._sections[section] = self._dict()

    def has_section(self, section):
        """Indicate whether the named section is present in the configuration.

        The DEFAULT section is not acknowledged.
        """
        return section in self._sections

    def options(self, section):
        """Return a list of option names for the given section name."""
        try:
            opts = self._sections[section].copy()
        except KeyError:
            raise NoSectionError(section)
        opts.update(self._defaults)
        if '__name__' in opts:
            del opts['__name__']
        return opts.keys()

    def read(self, filenames):
        """Read and parse a filename or a list of filenames.

        Files that cannot be opened are silently ignored; this is
        designed so that you can specify a list of potential
        configuration file locations (e.g. current directory, user's
        home directory, systemwide directory), and all existing
        configuration files in the list will be read.  A single
        filename may also be given.

        Return list of successfully read files.
        """
        if isinstance(filenames, basestring):
            filenames = [filenames]
        read_ok = []
        for filename in filenames:
            try:
                fp = open(filename)
            except IOError:
                continue
            self._sections = self._dict()
            self._read(fp, filename)
            fp.close()
            read_ok.append(filename)
        return read_ok

    def get(self, section, option):
        opt = option
        if section not in self._sections:
            if section != DEFAULTSECT:
                raise NoSectionError(section)
            if opt in self._defaults:
                return self._defaults[opt]
            else:
                raise NoOptionError(option, section)
        elif opt in self._sections[section]:
            return self._sections[section][opt]
        elif opt in self._defaults:
            return self._defaults[opt]
        else:
            raise NoOptionError(option, section)

    def items(self, section):
        try:
            d2 = self._sections[section]
        except KeyError:
            if section != DEFAULTSECT:
                raise NoSectionError(section)
            d2 = self._dict()
        d = self._defaults.copy()
        d.update(d2)
        if "__name__" in d:
            del d["__name__"]
        return d.items()

#    def _get(self, section, conv, option):
#        return conv(self.get(section, option))
#
#    def getint(self, section, option):
#        return self._get(section, int, option)
#
#    def getfloat(self, section, option):
#        return self._get(section, float, option)

    def has_option(self, section, option):
        """Check for the existence of a given option in a given section."""
        if not section or section == DEFAULTSECT:
            return option in self._defaults
        elif section not in self._sections:
            return False
        else:
            return (option in self._sections[section]
                    or option in self._defaults)

    def set(self, section, option, value=None):
        """Set an option."""
        if not section or section == DEFAULTSECT:
            sectdict = self._defaults
        else:
            try:
                sectdict = self._sections[section]
            except KeyError:
                raise NoSectionError(section)
        sectdict[option] = value

    def write(self, fp):
        """Write an .ini-format representation of the configuration state."""
        if self._defaults:
            fp.write("[%s]\n" % DEFAULTSECT)
            for (key, value) in self._defaults.items():
                fp.write("%s = %s\n" % (key, str(value).replace('\n', '\n\t')))
            fp.write("\n")
        for section in self._sections:
            fp.write("[%s]\n" % section)
            for (key, value) in self._sections[section].items():
                if key == "__name__":
                    continue
                if key == CONTENTBLOCK and section != SETUP:
                    key = value
                    fp.write("%s" % (key))
                elif (value is not None) or (self._optcre == self.OPTCRE):
                    key = "=".join((key, str(value).replace('\n', '\n\t')))
                    fp.write("%s\n" % (key))
            #fp.write("\n")

    def remove_option(self, section, option):
        """Remove an option."""
        if not section or section == DEFAULTSECT:
            sectdict = self._defaults
        else:
            try:
                sectdict = self._sections[section]
            except KeyError:
                raise NoSectionError(section)
        existed = option in sectdict
        if existed:
            del sectdict[option]
        return existed

    def remove_section(self, section):
        """Remove a file section."""
        existed = section in self._sections
        if existed:
            del self._sections[section]
        return existed

    #
    # Regular expressions for parsing section headers and options.
    #
    SECTCRE = re.compile(
        r'\['                                 # [
        r'(?P<header>[^]]+)'                  # very permissive!
        r'\]'                                 # ]
        )
    OPTCRE = re.compile(
        r'(?P<option>[^:=\s][^:=]*)'          # very permissive!
        r'\s*(?P<vi>[:=])\s*'                 # any number of space/tab,
                                              # followed by separator
                                              # (either : or =), followed
                                              # by any # space/tab
        r'(?P<value>.*)$'                     # everything up to eol
        )
    OPTCRE_NV = re.compile(
        r'(?P<option>[^:=\s][^:=]*)'          # very permissive!
        r'\s*(?:'                             # any number of space/tab,
        r'(?P<vi>[:=])\s*'                    # optionally followed by
                                              # separator (either : or
                                              # =), followed by any #
                                              # space/tab
        r'(?P<value>.*))?$'                   # everything up to eol
        )

    def _read(self, fp, fpname):
        """Parse a sectioned setup file.

        The sections in setup file contains a title line at the top,
        indicated by a name in square brackets (`[]'), plus key/value
        options lines, indicated by `name: value' format lines.
        Continuations are represented by an embedded newline then
        leading whitespace.  Blank lines, lines beginning with a '#',
        and just about everything else are ignored.
        """
        cursect = None                        # None, or a dictionary
        optname = None
        lineno = 0
        e = None                              # None, or an exception
        while True:
            line = fp.readline()
            if not line:
                break
            lineno = lineno + 1
            # comment or blank line?
            if line.strip() == '' or line[0] in '#;':
                if cursect is None or cursect['__name__'] == SETUP:
                    continue
            elif line.split(None, 1)[0].lower() == 'rem' and line[0] in "rR":
                # no leading whitespace
                continue
            # continuation line?
            if line[0].isspace() and cursect is not None and optname:
                value = line.strip()
                if value:
                    cursect[optname].append(value)
            # a section header or option header?
            else:
                # is it a section header?
                mo = self.SECTCRE.match(line)
                if mo:
                    sectname = mo.group('header')
                    if sectname in self._sections:
                        cursect = self._sections[sectname]
                    elif sectname == DEFAULTSECT:
                        cursect = self._defaults
                    else:
                        cursect = self._dict()
                        cursect['__name__'] = sectname
                        self._sections[sectname] = cursect
                    # So sections can't start with a continuation line
                    optname = None
                # no section header in the file?
                elif cursect is None:
                    raise MissingSectionHeaderError(fpname, lineno, line)
                elif cursect['__name__'] != SETUP:
                    #code = cursect.get('code', [])
                    #cursect['code'] = code.append(line)
                    cursect[CONTENTBLOCK] = cursect.get(CONTENTBLOCK, '') + line
                # an option line?
                else:
                    mo = self._optcre.match(line)
                    if mo:
                        optname, vi, optval = mo.group('option', 'vi', 'value')
                        optname = optname.rstrip()
                        # This check is fine because the OPTCRE cannot
                        # match if it would set optval to None
                        if optval is not None:
                            if vi in ('=', ':') and ';' in optval:
                                # ';' is a comment delimiter only if it follows
                                # a spacing character
                                pos = optval.find(';')
                                if pos != -1 and optval[pos-1].isspace():
                                    optval = optval[:pos]
                            optval = optval.strip()
                            # allow empty values
                            if optval == '""':
                                optval = ''
                            cursect[optname] = [optval]
                        else:
                            # valueless option handling
                            cursect[optname] = optval
                    else:
                        # a non-fatal parsing error occurred.  set up the
                        # exception but keep going. the exception will be
                        # raised at the end of the file and will contain a
                        # list of all bogus lines
                        if not e:
                            e = ParsingError(fpname)
                        e.append(lineno, repr(line))
        # if any parsing errors occurred, raise an exception
        if e:
            raise e

        # join the multi-line values collected while reading
        all_sections = [self._defaults]
        all_sections.extend(self._sections.values())
        for options in all_sections:
            for name, val in options.items():
                if isinstance(val, list):
                    options[name] = '\n'.join(val)

import UserDict as _UserDict

class _Chainmap(_UserDict.DictMixin):
    """Combine multiple mappings for successive lookups.

    For example, to emulate Python's normal lookup sequence:

        import __builtin__
        pylookup = _Chainmap(locals(), globals(), vars(__builtin__))
    """

    def __init__(self, *maps):
        self._maps = maps

    def __getitem__(self, key):
        for mapping in self._maps:
            try:
                return mapping[key]
            except KeyError:
                pass
        raise KeyError(key)

    def keys(self):
        result = []
        seen = set()
        for mapping in self._maps:
            for key in mapping:
                if key not in seen:
                    result.append(key)
                    seen.add(key)
        return result


    def get(self, section, option):
        """Get an option value for a given section.

        The section DEFAULT is special.
        """
        sectiondict = {}
        try:
            sectiondict = self._sections[section]
        except KeyError:
            if section != DEFAULTSECT:
                raise NoSectionError(section)
        # Update with the entry specific variables
        vardict = {}
        if vars:
            for key, value in vars.items():
                vardict[key] = value
        d = _Chainmap(vardict, sectiondict, self._defaults)
        try:
            value = d[option]
        except KeyError:
            raise NoOptionError(option, section)
        return value

class ISSParser(ConfigParser):
    def getSetupOption(self, key):
        return self.get('Setup', key)
    
    def setSetupOption(self, option, value):
        self.set('Setup', option, value)

    def getDirs(self):
        return self.get('Dirs', CONTENTBLOCK)

    def setDirs(self, value):
        return self.set('Dirs', CONTENTBLOCK, value)

    def getFiles(self):
        return self.get('Files', CONTENTBLOCK)

    def setFiles(self, value):
        self.set('Files', CONTENTBLOCK, value)

    def getLanguages(self):
        return self.get('Languages', CONTENTBLOCK)

    def setLanguages(self, value):
        return self.set('Languages', CONTENTBLOCK, value)

    def getRegistry(self):
        return self.get('Registry', CONTENTBLOCK) 

    def setRegistry(self, value):
        return self.set('Registry', CONTENTBLOCK, value)

    def getTasks(self):
        return self.get('Tasks', CONTENTBLOCK)

    def setTasks(self, value):
        return self.set('Tasks', CONTENTBLOCK, value)

    def getRun(self):
        return self.get('Run', CONTENTBLOCK)

    def setRun(self, value):
        return self.set('Run', CONTENTBLOCK, value)

    def getUninstallRun(self):
        return self.get('UninstallRun', CONTENTBLOCK)

    def setUninstallRun(self, value):
        return self.set('UninstallRun', CONTENTBLOCK, value)

    def getInstallDelete(self):
        return self.get('InstallDelete', CONTENTBLOCK)

    def setInstallDelete(self, value):
        return self.set('InstallDelete', CONTENTBLOCK, value)

    def getIcons(self):
        return self.get('Icons', CONTENTBLOCK)

    def setIcons(self, value):
        return self.set('Icons', CONTENTBLOCK, value)

    def getCode(self):
        return self.get('Code', CONTENTBLOCK)

    def setCode(self, value):
        return self.set('Code', CONTENTBLOCK, value)

    def writefile(self, path):
        with open(path, 'w') as fp:
            self.write(fp)
