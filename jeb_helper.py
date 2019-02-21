import sublime
import sublime_plugin
import os
import re
import string

'''
ST3 extensions to help with JEB Python script development
Nicolas Falliere - PNF Software

This ST3 extension provides:
- create a new JEB script from template (from the Command Palette)
- update the API documentation file (from the Command Palette)
- auto-completion helpers for types and attributes
- insert type import statement (key binding: Ctrl+Alt+I)
- browse JEB type documentation (key binding: Ctrl+Alt+J)
'''

g = None  # JebGlobals object holding JEB type info dictionaries

PACKAGE_NAME = 'JEB Script Development Helper'
APIDOCFILE = 'jeb-api.txt'
PACKAGE_API_RESPATH = 'Packages/' + PACKAGE_NAME + '/' + APIDOCFILE
USER_API_RESPATH = 'Packages/User/' + PACKAGE_NAME + '/' + APIDOCFILE
URLBASE = 'https://www.pnfsoftware.com'
URLBASE_APIDOC = URLBASE + '/jeb/apidoc'
URL_APIDOCFILE = URLBASE_APIDOC + '/' + APIDOCFILE
SETTINGS_NAME = PACKAGE_NAME + '.sublime-settings'

verbose = sublime.load_settings(SETTINGS_NAME).get('verbose')

#------------------------------------------------------------------------------
def log(s):
    if verbose:
        print('[JEB] %s' % s)

#------------------------------------------------------------------------------
def plugin_loaded():
    global g
    log('Loading plugin ...')
    g = JebGlobals()
    log('plugin_loaded() executed successfuly')

#------------------------------------------------------------------------------
def api_text():
    # prefer user API file over package-provided API file, likely to be older
    try:
        log('Using user (custom or updated) apidoc file')
        return sublime.load_resource('Packages/User/' + PACKAGE_NAME + '/' + APIDOCFILE)
    except IOError:
        log('Using package (standard) apidoc file')
        return sublime.load_resource('Packages/' + PACKAGE_NAME + '/' + APIDOCFILE)

#------------------------------------------------------------------------------
class JebGlobals:
    def __init__(self):
        self.actlist = []
        self.acmlist = []

        self.simpletypenames = {}
        self.typenames = {}
        self.methodnames = set()

        for line in api_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            elts = line.split(';')
            typetype = elts[0]
            category = int(elts[1])
            simpletypename = elts[2]
            packagename = elts[3]
            typename = elts[4]
            supertype = elts[5]
            interfaces = split(elts[6], '|')
            constructors = split(elts[7], '|')
            methods = split(elts[8], '|')
            fields = split(elts[9], '|')

            # TODO: process fields as well
            for method in (methods + constructors):
                pos = method.find('(')
                if pos < 0:
                    raise Exception('Bad method: ', method)
                mname = method[:pos]
                args = split(method[pos+1:method.find(')')], ',')
                mname_with_args = mname + '('
                mname_with_args_tpl = mname + '('
                for iarg, arg in enumerate(args):
                    if iarg >= 1:
                        mname_with_args += ', '
                        mname_with_args_tpl += ', '
                    argname = arg.split(':')[0]
                    mname_with_args += argname
                    mname_with_args_tpl += '${%d:%s}' % (iarg + 1, argname)
                    iarg += 1
                mname_with_args += ')'
                mname_with_args_tpl += ')'
                self.methodnames.add((mname_with_args, mname_with_args_tpl, simpletypename))

            record = {
                'typetype': typetype,
                'category': category,
                'simpletypename': simpletypename,
                'packagename': packagename,
                'typename': typename,
                'supertype': supertype,
                'interfaces': interfaces,
                'constructors': constructors,
                'methods': methods,
                'fields': fields,
            }
            self.simpletypenames[simpletypename] = typename  #TODO: collisions!
            self.typenames[typename] = record

            # auto-completion for types
            hint = typename.replace('com.pnfsoftware.jeb.', '')
            self.actlist.append([simpletypename + '\t' + hint, simpletypename])

        # auto-completion for methods
        for mname_with_args, mname_with_args_tpl, simpletypename in self.methodnames:
            self.acmlist.append([mname_with_args + '\t' + simpletypename, mname_with_args_tpl])

#------------------------------------------------------------------------------
class JebAutocomplete(sublime_plugin.EventListener):
    # note: do not initialize in __init__, the API may not be available
    def on_query_completions(self, view, prefix, locations):
        #log('on_query_completions()')
        #log('  prefix=%s' % prefix)
        #log('  locations=%s' % locations)
        pos = locations[0]
        line, offset_in_line = get_line_and_offset(view, pos)
        #log('  -> "%s"' % line)
        #log('  ->  %s^' % (' ' * offset_in_line))
        if line.find('.') < 0 or line[offset_in_line - 1] in (' ', '\t'):
            r = g.actlist
        else:
            r = g.acmlist
        return r

#------------------------------------------------------------------------------
class JebScriptAddImportCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        current_word = get_current_word(self.view)
        log('Current word: `%s`' % current_word)
        if current_word:
            t = g.simpletypenames.get(current_word)
            if t:
                log(t)
                pos = t.rfind('.')
                pname = t[0:pos]  # careful, not necessarily a Java package (eg, for nested types)
                tname = t[pos + 1:]
                impline = 'from %s import %s' % (pname, tname)

                foundimport = False
                point = 0
                inspoint = 0
                buf = get_buffer(self.view)
                for i, line in enumerate(buf.splitlines(True)):
                    line2 = line.strip()
                    if not line2 or line2.startswith('#'):
                        if foundimport:
                            break
                        inspoint += len(line)
                    else:
                        if line2.startswith('from ') or line2.startswith('import '):
                            if line2 == impline:
                                inspoint = None
                                break
                            foundimport = True
                            inspoint += len(line)
                        else:
                            break
                    point += len(line)

                if inspoint != None:
                    self.view.insert(edit, inspoint, impline + '\n')

#------------------------------------------------------------------------------
class JebViewDocCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        current_word = get_current_word(self.view)
        log('Current word: `%s`' % current_word)
        if current_word:
            t = g.simpletypenames.get(current_word)
            if t:
                r = g.typenames[t]
                #log('Type information: %s' % r)
                import webbrowser
                addr = r['packagename'].replace('.', '/')
                addr += '/' + t[len(r['packagename']) + 1:]
                addr += '.html'
                url = URLBASE_APIDOC + '/reference/' + addr
                log('Navigating to: %s' % url)
                webbrowser.open_new_tab(url)

#------------------------------------------------------------------------------
class JebCreateNewScriptCommand(sublime_plugin.WindowCommand):
    def run(self, name):
        contents = '''# -*- coding: utf-8 -*-
from com.pnfsoftware.jeb.client.api import IScript
"""
Script for JEB Decompiler.
Note: This file must be saved as '%s.py'
"""

class %s(IScript):

\t# ctx: IClientContext
\tdef run(self, ctx):
\t\tpass
''' % (name, name)
        self.window.run_command('new_file')
        # retrieve the newly-created buffer
        v = self.window.active_view()
        v.settings().set('auto_indent', False)
        v.run_command('insert', {'characters': contents})

    #def description(self):
    #    return None

    # called only if the command is executed from the Command Palette
    def input(self, args):
        class Name(sublime_plugin.TextInputHandler):
            def initial_text(self):
                return 'JebSampleScriptName'
            def preview(self, text):
                if not isValidJebScriptName(text):
                    return 'Illegal script name! It must be a legal Python class name, consisting of letters and digits only.'
            def validate(self, text):
                return isValidJebScriptName(text)
        return Name()

#------------------------------------------------------------------------------
class JebUpdateApidocFile(sublime_plugin.WindowCommand):
    def run(self):
        import urllib.request
        import shutil
        url = URL_APIDOCFILE
        folder = os.path.join(sublime.packages_path(), 'User', PACKAGE_NAME)
        if not os.path.exists(folder):
            os.mkdir(folder)
        filename = os.path.join(folder, APIDOCFILE)
        with urllib.request.urlopen(url) as response, open(filename, 'wb') as outfile:
            shutil.copyfileobj(response, outfile)
        print('%s: Updated to latest version' % filename)

#------------------------------------------------------------------------------
def get_buffer(view):
    return view.substr(sublime.Region(0, view.size()))

#------------------------------------------------------------------------------
def get_line_and_offset(view, buffer_offset):
    lineregion = view.line(buffer_offset)
    lineoffset = lineregion.begin()
    offset_in_line = buffer_offset - lineoffset
    line = view.substr(lineregion)
    return (line, offset_in_line)

#------------------------------------------------------------------------------
def get_current_word(view):
    region = view.sel()[0]
    pos = region.begin()
    #log('caret@ %d' % pos)
    lineregion = view.line(region)
    #log('line: %s' % lineregion)
    lineoffset = lineregion.begin()
    offset_in_line = pos - lineoffset
    line = view.substr(lineregion)
    #line = line[0:offset_in_line]
    return get_word(line, offset_in_line)

#------------------------------------------------------------------------------
# dir: 0:right+left, -1:Left, +1:right
def get_word(line, offset_in_line, dir=0):
    i = offset_in_line
    if dir >= 0:
        while i < len(line):
            if not is_classname_character(line[i]):
                break
            i += 1
    else:
        if offset_in_line < len(line) and is_classname_character(line[offset_in_line]):
            return None

    i0 = offset_in_line - 1
    if dir <= 0:
        while i0 >= 0:
            if not is_classname_character(line[i0]):
                break
            i0 -= 1
    else:
        if i0 >= 0 and is_classname_character(line[i0]):
            return None

    return line[i0+1:i]

#------------------------------------------------------------------------------
# restrictive charset for names
alphabet = set(string.ascii_uppercase + string.ascii_lowercase)
alphanums = set(string.ascii_uppercase + string.ascii_lowercase + string.digits)
javachars = set(string.ascii_uppercase + string.ascii_lowercase + string.digits + '_')
def is_classname_character(c):
    # note: first char should not be a digit, ignore
    return c in javachars
def isValidJebScriptName(s):
    # note: underscore could be allowed
    if not s:
        return False
    if s[0] not in alphabet:
        return False
    i = 1
    while i < len(s):
        c = s[i]
        if c not in alphanums:
            return False
        i += 1
    return True

#------------------------------------------------------------------------------
# string splitter that returns an empty list if the string to be split is empty
# (note: string.split() returns a one-element list - the empty string - when splitting the empty string)
def split(s, delim):
    return [] if s == '' else s.split(delim)