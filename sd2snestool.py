#!/usr/bin/env python

import os
import re
import copy
import curses
import curses.textpad
import curses.ascii
import datetime
import json
import subprocess
import sys
import tempfile
import textwrap
import traceback

from collections import Mapping
from collections import OrderedDict
from fnmatch import fnmatch
from enum import Enum

curses.initscr()

COLORS = 0
LOG_PATH = None
UTF = True
BORDER_ARGS = [] if UTF else ['|', '|', '_', '_', ' ', ' ', '|', '|']
SHADOW = curses.ACS_CKBOARD
SCROLL_PAD_MAX = 20000  # protects against really long lists in the ui
APPS = 'this is a list of apps'.split(' ')
AREAS = os.listdir('/')
AW = min(max([len(a) for a in AREAS]), 50)
FILTER_MODE = 'normal'
WINDOW_SIZE = (100, 100)
           
with open('/home/Patrick/repos/sd2snestool/sd2snestool.py', 'r') as f:
    HELP = f.read()

class Quit(Exception):
    pass

class Echo(object):
    PATH = LOG_PATH

    def __init__(self, *strings):
        if self.PATH:
            with open(self.PATH, "a") as fo:
                string = ' '.join([str(i) for i in strings])
                fo.write(string + '\n')
        else:
            print ' '.join([str(i) for i in strings])

    @classmethod
    def clear(cls):
        with open(cls.PATH, "w") as fo:
            fo.write('\n')

class WriteOutputFile(Echo):
    PATH = None

# --------------------------------------------------------------------------- #
# - Colors
# --------------------------------------------------------------------------- #

class GuiColors(object):

    _col = {}
    _col = _col if isinstance(_col, dict) else dict()

    # Defaults when 8 colors available
    BG_TEXT_8 = curses.COLOR_CYAN
    BG_8 = curses.COLOR_BLUE
    PAGE_8 = curses.COLOR_WHITE
    SHADOW_8 = curses.COLOR_BLACK
    TEXT_8 = curses.COLOR_BLACK
    UNFOCUS_8 = curses.COLOR_BLUE
    FOCUS_8 = curses.COLOR_RED

    # Defaults when 256 colors available
    BG_TEXT_256 = 0
    BG_256 = 235
    PAGE_256 = 234
    SHADOW_256 = 232
    TEXT_256 = 36
    UNFOCUS_256 = 25
    FOCUS_256 = 43

    # Apply User Defaults
    BG_TEXT = BG_TEXT_8, _col.get('BG_TEXT', BG_TEXT_256)
    BG = BG_8, _col.get('BG', BG_256)
    PAGE = PAGE_8, _col.get('PAGE', PAGE_256)
    SHADOW = SHADOW_8, _col.get('SHADOW', SHADOW_256)
    TEXT = TEXT_8, _col.get('TEXT', TEXT_256)
    UNFOCUS = UNFOCUS_8, _col.get('UNFOCUS', UNFOCUS_256)
    FOCUS = FOCUS_8, _col.get('FOCUS', FOCUS_256)

class PaletteMixin(object):

    def info(self):

        print self.indexOf(self),
        print self,
        print self.value

    def start(self, screen):
        index = self.indexOf(self)
        screen.attron(curses.color_pair(index))

    def end(self, screen):
        index = self.indexOf(self)
        screen.attroff(curses.color_pair(index))

    @classmethod
    def indexOf(cls, obj):
        return list(cls).index(obj) + 1

    @property
    def pair(self):
        index = self.indexOf(self)
        return curses.color_pair(index)

    def fillScreen(self, screen, char=' ', attrs=None):
        index = self.indexOf(self)
        if attrs is not None:
            screen.bkgd(char, curses.color_pair(index) | attrs)
        else:
            screen.bkgd(char, curses.color_pair(index))

    @classmethod
    def initPairs(cls):
        curses.start_color()
        if not curses.has_colors():
            return
        for i, val in enumerate(cls, 1):
            numcolors = COLORS or curses.COLORS
            if numcolors < 8:
                pair = curses.COLOR_WHITE, curses.COLOR_BLACK
            elif numcolors < 256:
                pair = list(val.value)[:2]
            else:
                pair = list(val.value)[-2:]
            curses.init_pair(i, *pair)

class Color(PaletteMixin, Enum):
    """ Hacked Enum """
    BG = (
        GuiColors.BG_TEXT[0], GuiColors.BG[0],
        GuiColors.BG_TEXT[-1], GuiColors.BG[-1])
    WINDOW_FOCUSED = (
        GuiColors.FOCUS[0], GuiColors.PAGE[0],
        GuiColors.FOCUS[-1], GuiColors.PAGE[-1])
    WINDOW_OFF = (
        GuiColors.UNFOCUS[0], GuiColors.PAGE[0],
        GuiColors.UNFOCUS[-1], GuiColors.PAGE[-1])
    SHADOW = (
        GuiColors.SHADOW[0], GuiColors.SHADOW[0],
        GuiColors.SHADOW[-1], GuiColors.SHADOW[-1])
    TEXT = (
        GuiColors.TEXT[0], GuiColors.PAGE[0],
        GuiColors.TEXT[-1], GuiColors.PAGE[-1])
    HIGHLIGHT = (
        GuiColors.FOCUS[0], GuiColors.PAGE[0],
        GuiColors.FOCUS[-1], GuiColors.PAGE[-1])
    SELECTED = (
        GuiColors.UNFOCUS[0], GuiColors.PAGE[0],
        GuiColors.UNFOCUS[-1], GuiColors.PAGE[-1])

# --------------------------------------------------------------------------- #
# - Oz Tools                                                                - #
# --------------------------------------------------------------------------- #

class Keys(object):
    KEY_ENTER = ord('\n')
    KEY_RESIZE = curses.KEY_RESIZE
    KEY_MOUSE = curses.KEY_MOUSE

    # I can't find a curses index for these 2
    # Need to ask someone else if it works for them
    KEY_WHEEL_UP = 524288
    KEY_WHEEL_DOWN = 134217728

    RESIZE = (curses.KEY_RESIZE,)
    MOUSE = (curses.KEY_MOUSE,)

    ENTER = (curses.ascii.CR, curses.ascii.LF, ord('o'))
    PAGE_UP = (curses.KEY_PPAGE,)  # + ctrl+b, ctrl+f
    PAGE_DOWN = (curses.KEY_NPAGE,)
    TOP = (ord('g'), curses.KEY_HOME)
    BOTTOM = (ord('G'), curses.KEY_END)

    UP = (curses.KEY_UP, ord('k'))
    DOWN = (curses.KEY_DOWN, ord('j'))
    LEFT = (curses.KEY_LEFT, ord('h'))
    RIGHT = (curses.KEY_RIGHT, ord('l'))
    FIND = (ord('f'), ord('/'))
    CANCEL = (curses.ascii.ESC,)
    DELETE = (
        curses.ascii.BS,
        curses.ascii.DEL,
        curses.KEY_BACKSPACE,
        curses.KEY_DC,
        ord('x'),
    )
    SAVE = (ord('s'),)
    UPDATE = (ord('u'),)
    INSERT = (ord('i'),)
    QUIT = (ord('q'),)

    EXECUTE = (ord('e'),)
    SET_NAME = (ord('n'), ord('t'))
    SET_MODE = (ord('m'),)
    SHOW_HIST = (ord('h'), ord('H'))
    SHOW_HIST_GLOBAL = (ord('H'),)

    CLEAR_SCREEN = (ord('c'),)

    TAB_HELP = (curses.KEY_F1, ord('1'))
    TAB_CURRENT = (curses.KEY_F2, ord('2'))
    TAB_ALL = (curses.KEY_F3, ord('3'))
    TAB_SAVED = (curses.KEY_F4, ord('4'))
    TAB_ENVINFO = (curses.KEY_F5, ord('5'))
    TAB_PREV = (ord(','),)
    TAB_NEXT = (ord('.'),)
    DUMP_PAK = (ord('D'),)
    EDIT_PAK = (ord('E'),)

class OzHelper(object):

    ORGANIZATION = 'LEI'
    APPLICATION = 'ozzerGuiKonsole'
    AREA_PROJECTS = ['avtr']
    USE_QSETTINGS = True

    def __init__(self):

        self.addPaks = []
        self.removePaks = []
        self.myPaks = []
        self.ozmode = 'oz'
        self.tabName = 'oz'
        self.ozStash = []
        self.oz = None

        self._loadSettings()
        self._loadStash()

    # - Class Helpers ------------------------------------------------------- #

    def _getQSettings(self, group):

        return {}

    def _saveQSettings(self, settingsToSave, group):
        """settings should be json serialize-able"""
        return

    def _loadSettings(self):
        uiData = self._getQSettings('UI')
        for key, value in uiData.items():
            setattr(self, key, value)

    def _loadStash(self):
        stashData = self._getQSettings('builderUI')
        self.ozStash = [json.loads(i) for i in stashData]

    def _getSettingsDict(self):
        """ gets current settings as dict"""

        return copy.deepcopy(dict(
            addPaks=self.addPaks,
            removePaks=self.removePaks,
            ozmode=self.ozmode,
            tabName=self.tabName,
            myPaks=self.myPaks))

    @staticmethod
    def _getAppVersionsUnsorted(app):

        for i in []:
            yield True

    # - Oz Helpers ---------------------------------------------------------- #

    @classmethod
    def getAllAreas(cls):
        areas = []
        return areas

    @staticmethod
    def getPakApp(pakNameVersion):
        """ gets the pak name for a pak-version string
        eg. "Gazebo-0.0.0" would return "Gazebo"
        """
        return 'wat'

    @classmethod
    def getAppVersions(cls, app):
        def keyfunc(string):
            string = string.replace('-', '.')
            string = [i.zfill(4) for i in string.split('.')]
            return ''.join(string)
        if app:
            return sorted(list(cls._getAppVersionsUnsorted(app)), key=keyfunc)

    @classmethod
    def pakDump(cls, inputPak):
        """Dump the contents of specified App Versions to JSON"""

    @classmethod
    def savePakFromJson(cls, newJsonStr):
        """Save pak from string
        Returns:
            False if no error otherwise returns the error
        """

    # - Tool Methods -------------------------------------------------------- #

    def saveCurrentSettings(self):
        """ updates qsettings with current env"""
        self._saveQSettings(self._getSettingsDict(), 'UI')

    def getOzCommand(self, settingsDict=None, quiet=False):
        """returns current env as a runnable command"""

        settingsDict = settingsDict or self._getSettingsDict()

        ozmode = settingsDict.get('ozmode', 'oz')
        addPaks = settingsDict.get('addPaks', [])
        removePaks = settingsDict.get('removePaks', [])
        tabName = settingsDict.get('tabName', 'Unnamed')

        addText = ' --add '.join(addPaks)
        addText = ' --add ' + addText if addText else ''
        removeText = ' --remove '.join(removePaks)
        removeText = ' --remove ' + removeText if removeText else ''
        qstring = ' -q' if quiet else ''

        return tabName, ozmode + qstring + addText + removeText

    def addPak(self, pakNameVersion):
        """adds a pack to the current env"""
        if pakNameVersion:
            app = self.getPakApp(pakNameVersion)
            addApps = [self.getPakApp(p) for p in self.addPaks]
            removeApps = [self.getPakApp(p) for p in self.removePaks]
            if app in removeApps:
                self.removePak(pakNameVersion)
            if app in addApps:
                index = addApps.index(app)
                self.addPaks[index] = pakNameVersion
            else:
                self.addPaks.append(pakNameVersion)

    def removePak(self, pakNameVersion):
        """removes a pak from the current env"""
        if pakNameVersion in self.addPaks:
            self.addPaks.remove(pakNameVersion)
        if pakNameVersion in self.removePaks:
            self.removePaks.remove(pakNameVersion)

    # - Stash  Methods ------------------------------------------------------ #

    def saveStashedEnvs(self):
        """ saves stash to qsettings """
        jsonStash = [json.dumps(o) for o in self.ozStash]
        self._saveQSettings(jsonStash, 'builderUI')

    def getStashStrings(self):
        """ returns a list of stashed envs printable """
        if not self.ozStash:
            return []
        results = []
        cmds = [self.getOzCommand(i) for i in self.ozStash]
        _max = max([len(i) for i, j in cmds])
        fmt = '{:>2} {:%s} | {}' % _max
        for i, (name, cmd) in enumerate(cmds):
            results.append(fmt.format(i, name, cmd))
        return results

    def loadStashedEnv(self, index):
        """ updates current env with stashed index """

        if index is None:
            return

        validKeys = ['addPaks', 'removePaks', 'myPaks', 'ozmode', 'tabName']
        for key, value in self.ozStash[index].items():
            if key in validKeys:
                setattr(self, key, copy.deepcopy(value))

    def addStashedEnv(self):
        """ saves current env to stash list """
        self.ozStash.append(self._getSettingsDict())

    def updatedStashedEnv(self, index):
        """ saves current env to stash index """

        if index is None:
            return

        self.ozStash[index] = self._getSettingsDict()

    def insertStashedEnv(self, index):
        """ insert current env at stash index """
        self.ozStash.insert(index, self._getSettingsDict())

    def popStashedEnv(self, index):
        """ removes a stash index """
        return self.ozStash.pop(index)

    # - Other --------------------------------------------------------------- #

    def parseString(self, string):
        """parse a command line string"""
        import argparse
        string = [o for o in re.findall('\S+', string) if not o == 'oz']
        parser = argparse.ArgumentParser()
        parser.add_argument('area', nargs='*', action='store', default='')
        parser.add_argument('-a', '--add', action='append', default=[])
        parser.add_argument('-r', '--remove', action='append', default=[])
        result = parser.parse_args(string)
        if len(result.area) > 1:
            Echo('Too many areas', result.area)
            return
        self.ozmode = 'oz ' + result.area[0] if result.area else self.ozmode
        self.addPaks = result.add
        self.removePaks = result.remove

    def envInfo(self, ozCommand=None):
        """ get the paks for the current env

        executes bash interactively in a subshell and runs the current oz
        command, this is slow but it seems it's the only reliable way to expand
        our LEI aliases.

        ozCommand(string):
            a string that you would put on the shell such as "laboz", if None,
            the current class env will be used.

        Returns:
            a list of app-version (pak) strings

        """
        name, ozcmd = self.getOzCommand()
        cmd = ozcmd + ' > /dev/null && echo $_OZ_ALL'
        pipes = subprocess.Popen(
            ['/bin/bash', '-i', '-c', cmd],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        std_out, std_err = pipes.communicate()
        if not '[ERROR]' in std_err and pipes.returncode == 0:
            return std_out.strip().split(',')
        else:  # an error happend
            std_err = '\n'.join(textwrap.wrap(std_err))
            raise RuntimeError(std_err)

def stripRmItmPrefix(string):
    return string

def setCursor(mode):
    try:
        curses.curs_set(mode)
    except curses.error:
        pass

# --------------------------------------------------------------------------- #
# - Widgets                                                                 - #
# --------------------------------------------------------------------------- #

class Widget(object):
    """ not sure if this really counts as a widget
    creates a template for drawing in curses
    """

    def __init__(self, parent):
        self.parentWidget = parent
        self.parent = parent.getWindow()
        self.title = None
        self.window = self.newwin()

    def getStdscreen(self):
        """TODO kinda sux"""

        p = self.parentWidget
        while p:
            if hasattr(p, 'parentWidget'):
                p = p.parentWidget
            else:
                if hasattr(p, 'stdscr'):
                    return p.stdscr
                break

    def refreshTop(self):
        """ refreshes the top most window "MainWindow"
        NOTE: this will only work if all parents in tact
        """
        p = self.parentWidget
        while p:
            if hasattr(p, 'parentWidget'):
                p = p.parentWidget
            else:
                p.draw(refresh=True)
                break

    @staticmethod
    def newwin():
        return curses.newwin(1, 1, 0, 0)

    def parentSize(self):
        return self.parent.getmaxyx()

    def parentPos(self):
        return self.parent.getbegyx()

    def processKeypress(self, ch):
        pass

    def getWindow(self):
        """ the thing a child will look to as parent """
        return self.window

    def draw(self):
        """ draw function here """
        y, x = self.parentPos()
        h, w = self.parentSize()

        self.window.resize(h, w)
        self.window.mvwin(y, x)
        self.window.border(*BORDER_ARGS)

        _, ww = self.window.getmaxyx()
        if self.title:
            self.window.addnstr(0, 1, self.title, ww - 1)

    def doRefresh(self):
        """ noutrefresh-es go here"""
        self.window.noutrefresh()

    def mouseEvent(self, bstate, y, x, callback):
        if self.getWindow().enclose(y, x):
            if bstate in (curses.BUTTON1_CLICKED,
                          curses.BUTTON1_DOUBLE_CLICKED):
                if callback:
                    callback(y, x)

class BlankWid(Widget):

    def draw(self):
        """ draw function here """
        y, x = self.parentPos()
        h, w = self.parentSize()
        self.window.resize(h, w)
        self.window.mvwin(y, x)

    def doRefresh(self):
        """ noutrefresh-es go here"""

class CSizeWid(Widget):
    """centered window widget with target size"""

    def __init__(self, parent):
        self.parentWidget = parent
        self.parent = parent.getWindow()
        self.window = self.newwin()
        self.targetHeight = 10
        self.targetWidth = 30
        self.show = True

    def draw(self):
        """ draw function here """
        py, px = self.parentPos()
        ph, pw = self.parentSize()

        h = min(ph, self.targetHeight)
        w = min(pw, self.targetWidth)

        y = ph // 2 - h // 2
        x = pw // 2 - w // 2

        self.window.resize(h, w)
        self.window.mvwin(y + py, x + px)

    def doRefresh(self):
        """ noutrefresh-es go here"""
        if self.show:
            self.window.noutrefresh()

class TabBar(Widget):

    def __init__(self, parent):

        self.parentWidget = parent
        self.parent = parent.getWindow()
        self.window = self.newwin()
        self.title = None
        self.items = ['tab1', 'tab2', 'tab3']
        self.tabIndex = 0
        self.focus = False
        self.itemBounds = []

    def getWindow(self):
        """ the thing a child will look to as parent """
        return self.window

    def draw(self):
        """ draw function here """
        y, x = self.parentPos()
        h, w = self.parentSize()
        self.itemBounds = []

        self.window.resize(1, w)
        self.window.mvwin(y, x)
        Color.BG.fillScreen(self.window)

        wh, ww = self.window.getmaxyx()
        curw = 0
        for i, item in enumerate(self.items):

            if i == self.tabIndex:
                color = Color.TEXT.pair | curses.A_REVERSE
            else:
                color = Color.TEXT.pair
            if self.focus:
                color |= curses.A_BOLD

            item = str(' ' + item + ' ')
            if curw + len(item) > ww - 2:
                left = ww - curw - 2
                self.window.addnstr(0, curw, item, left, color)
                break
            self.window.addstr(0, curw, item, color)
            gcurw = curw + x - 1
            self.itemBounds.append((i, gcurw, gcurw + len(item) + 1))
            curw += len(item)

        self.window.resize(1, max(1, curw))

    def doRefresh(self):
        """ noutrefresh-es go here"""
        self.window.noutrefresh()

    def mouseEvent(self, bstate, y, x, callback):

        if self.getWindow().enclose(y, x):
            if bstate in (curses.BUTTON1_CLICKED,
                          curses.BUTTON1_DOUBLE_CLICKED):
                for index, start, end in self.itemBounds:
                    if x > start and x < end:
                        callback(index)

class DropShadowWid(Widget):
    """ its has a drop shadow
    """

    def __init__(self, parent):

        self.parentWidget = parent
        self.parent = parent.getWindow()
        self.focus = False
        self.title = None
        self.dropShadowOutside = False

        self.fg = self.newwin()
        self.bg = self.newwin()
        self.contents = self.newwin()

        Color.WINDOW_OFF.fillScreen(self.fg)
        Color.SHADOW.fillScreen(self.bg, SHADOW)

    def getWindow(self):
        return self.contents

    def draw(self):
        """ draw function here """

        if not self.focus:
            Color.WINDOW_OFF.fillScreen(self.fg)
        else:
            attrs = curses.A_BOLD
            Color.WINDOW_FOCUSED.fillScreen(self.fg, attrs=attrs)

        y, x = self.parentPos()
        h, w = self.parentSize()

        self.fg.erase()
        self.bg.erase()
        self.contents.erase()

        gh, gw = self.getStdscreen().getmaxyx()
        wh = h if self.dropShadowOutside else h - 1
        ww = w if self.dropShadowOutside else w - 1
        self.fg.resize(wh, ww)
        self.bg.resize(min(wh, gh - 1), min(ww, gw - 1))
        self.contents.resize(max(h - 3, 1), max(w - 3, 1))

        self.fg.mvwin(y, x)
        self.bg.mvwin(y + 1, x + 1)
        self.contents.mvwin(y + 1, x + 1)

        self.fg.border(*BORDER_ARGS)

        if self.title:
            self.fg.addnstr(0, 1, self.title, w - 1)

    def doRefresh(self):
        """ noutrefresh-es go here"""
        self.bg.noutrefresh()
        self.fg.noutrefresh()

class FrameWid(Widget):
    """ drop shadow wid with now shadow
    """

    def __init__(self, parent):

        self.parentWidget = parent
        self.parent = parent.getWindow()
        self.focus = False
        self.title = None

        self.fg = self.newwin()
        self.contents = self.newwin()

        Color.WINDOW_OFF.fillScreen(self.fg)

    def getWindow(self):
        return self.contents

    def draw(self):
        """ draw function here """

        if not self.focus:
            Color.WINDOW_OFF.fillScreen(self.fg)
        else:
            attrs = curses.A_BOLD
            Color.WINDOW_FOCUSED.fillScreen(self.fg, attrs=attrs)

        y, x = self.parentPos()
        h, w = self.parentSize()

        self.fg.erase()
        self.contents.erase()

        self.fg.resize(h, w)
        self.contents.resize(max(h - 2, 1), max(w - 2, 1))

        self.fg.mvwin(y, x)
        self.contents.mvwin(y + 1, x + 1)

        self.fg.border(*BORDER_ARGS)

        if self.title:
            self.fg.addnstr(0, 1, self.title, w - 1)

    def doRefresh(self):
        """ noutrefresh-es go here"""
        self.fg.noutrefresh()

class ScrollWid(Widget):

    def __init__(self, parent):

        self.parentWidget = parent
        self.parent = parent.getWindow()
        self.pad = self.newpad()
        self.padPos = [0, 0, 0, 0, 1, 1]
        self._pageScroll = 0
        self._scrollIndex = 0
        self._previousIndex = 0
        self._items = []
        self._visibleItems = []
        self.filterText = ''
        self.focus = False
        # if true, instead of scrolling by item, the whole page is scrolled and
        # no active item in highlighted.
        self.pageMode = False

    def _addItemStr(self, y, x, text, maxw=None, onlyfocus=False):

        if self.pageMode:
            color = 0
        elif self.focus:
            color = Color.HIGHLIGHT.pair | curses.A_REVERSE
        else:
            if not onlyfocus:
                color = Color.SELECTED.pair | curses.A_REVERSE
            else:
                color = 0

        if y == self._scrollIndex:
            color = color
        else:
            color = 0

        self.pad.addstr(y, x, text, color)

    def currentItem(self):
        if self._visibleItems:
            return self._visibleItems[self._scrollIndex]

    def getWindow(self):
        return self.parent

    def textFilter(self, item):

        return self.filterText.strip().lower() in item.lower()

    def regexFilter(self, item):

        return bool(re.search(self.filterText.strip(), item, re.IGNORECASE))

    def globFilter(self, item):

        match = self.filterText.strip().lower()
        return True if not match else fnmatch(item.lower(), match)

    def setItems(self, itemList=None):

        itemList = self._items if itemList is None else itemList

        # TODO: keep scroll on filter
        self._pageScroll = 0
        self._scrollIndex = 0
        self._previousIndex = 0
        self._items = itemList
        self.padPos[0] = self._pageScroll

        if FILTER_MODE == 'regex':
            self._visibleItems = itemList = filter(self.regexFilter, itemList)
        elif FILTER_MODE == 'glob':
            self._visibleItems = itemList = filter(self.globFilter, itemList)
        else:
            self._visibleItems = itemList = filter(self.textFilter, itemList)

        self.pad.erase()

        # resize the pad
        if itemList:
            # writing to the lower right corner creates an error in curses
            # in order to work around this we will add an empty line
            pad_y = len(itemList) + 1
            pad_x = max(max([len(i) for i in itemList]), 1)
            self.pad.resize(min(pad_y, SCROLL_PAD_MAX), pad_x)
            py, px = self.pad.getmaxyx()
            if py < 0:
                Echo ('PAD NEG', pad_y, pad_x)
        else:
            pad_x = 1
            self.pad.resize(1, 1)

        # get the resized pad, if the list is too long the pad will not be able
        # to scale up to the size of the pad, and the GUI will error
        py, px = self.pad.getmaxyx()
        for i, thing in enumerate(itemList):
            if i >= py:  # the pad wasn't big enough, time to bail
                # Echo ('Warning: too many items, list incomplete.')
                # Echo ('items=%s padsizey=%s len(itemList)=%s' % (
                #       i, py, len(itemList)))
                break

            self._addItemStr(i, 0, thing, pad_x)

    def getItems(self, visibleOnly=False):

        if visibleOnly:
            return self._visibleItems
        else:
            return self._items

    @staticmethod
    def newpad():

        pad = curses.newpad(1, 1)
        Color.TEXT.fillScreen(pad)
        return pad

    def draw(self, onlyfocus=False):
        """ draw function here """

        y, x = self.parentPos()
        h, w = self.parentSize()

        pminrow = self._pageScroll
        pmincol = 0
        sminrow = y
        smincol = x
        smaxrow = h + y - 1
        smaxcol = w + x - 1

        if onlyfocus:
            smaxrow -= 3

        self.padPos = [
            pminrow, pmincol,  # real position of pad
            sminrow, smincol,  # draw start
            smaxrow, smaxcol]  # draw end

        if self._visibleItems:
            self._addItemStr(
                self._scrollIndex, 0,
                self._visibleItems[self._scrollIndex],
                onlyfocus=onlyfocus)

    def pageSize(self):

        (scroll, pmincol,
         sminrow, smincol,
         smaxrow, smaxcol) = self.padPos
        return smaxrow - sminrow + 1

    def pageScrollRemaining(self):
        """return the number of items that can be on screen

             -----------------
        0x0-> padx or padx    1    pad of 7x4
        1   | xxxx    xxxx    2    h = 11
        2   | xxxx    xxxx    3    padh = 7
        3   | xxxx    xxxx    4
        4   | xxxx    xxxx    5
        etc | xxxx    xxxx    6
            | xxxx    xxxx    7
            | xxxx      -4    8
            | xxxx      -3  <----- margin
            | xxxx      -2    10
            | xxxx      -1    11
             -xxxx-------0----
              xxxx       1  <----- leftover
              xxxx       2

        """
        scroll = self._pageScroll
        contentH, _ = self.pad.getmaxyx()
        pageSize = self.pageSize()
        margin = max(pageSize - contentH, 0)
        leftover = margin + contentH - pageSize
        return leftover - scroll

    def scroll(self, amount):

        if self.pageMode:
            self.pageScroll(amount)
            return

        pageSize = self.pageSize()
        h, w = self.pad.getmaxyx()

        if not self._visibleItems:
            return

        self._previousIndex = self._scrollIndex
        self._scrollIndex += amount
        self._scrollIndex = max(self._scrollIndex, 0)
        self._scrollIndex = min(self._scrollIndex, h - 2)

        pageStart = self._pageScroll
        pageEnd = self._pageScroll + pageSize - 1

        if self._scrollIndex > pageEnd:
            self.pageScroll(self._scrollIndex - pageEnd)
        if self._scrollIndex < pageStart:
            self.pageScroll(self._scrollIndex - pageStart)

        self._addItemStr(
            self._previousIndex, 0,
            self._visibleItems[self._previousIndex])
        self._addItemStr(
            self._scrollIndex, 0,
            self._visibleItems[self._scrollIndex])

        self.doRefresh()

    def pageScroll(self, amount):

        self._pageScroll += amount

        # keep the items on the page
        self._pageScroll = max(self._pageScroll, 0)
        self._pageScroll += min(0, self.pageScrollRemaining())

        self.padPos[0] = self._pageScroll
        self.pad.redrawwin()

    def doRefresh(self):
        """ noutrefresh-es go here"""
        try:
            self.pad.noutrefresh(*self.padPos)
        except curses.error as e:
            Echo('Invalid Scroll Size', e)

    def index(self):
        return self._scrollIndex

    def processKeypress(self, ch):

        y, x = self.getWindow().getmaxyx()
        contentH, _ = self.pad.getmaxyx()

        if ch in Keys.PAGE_UP:
            self.scroll(-y)

        elif ch in Keys.PAGE_DOWN:
            self.scroll(y)

        elif ch in Keys.UP:
            self.scroll(-1)

        elif ch in Keys.DOWN:
            self.scroll(1)

        elif ch in Keys.TOP:
            self.scroll(-contentH)

        elif ch in Keys.BOTTOM:
            self.scroll(contentH)

        elif ch in Keys.FIND:
            if not self.pageMode:
                popup = PopupEnterText(self)
                result = popup.execute()
                self.filterText = result
                self.setItems()

            # self.doRefresh()
            # self.draw()
            # self.doRefresh()

    def mouseEvent(self, bstate, y, x, callback):
        if bstate in (curses.BUTTON1_CLICKED,
                      curses.BUTTON1_DOUBLE_CLICKED):
            py, _ = self.parentPos()
            targetIndex = y - py + self.padPos[0]
            self.scroll(targetIndex - self._scrollIndex)
        elif bstate == Keys.KEY_WHEEL_UP:
            curses.ungetch(Keys.UP[0])
        elif bstate == Keys.KEY_WHEEL_DOWN:
            curses.ungetch(Keys.DOWN[0])

class ScrollWidU(ScrollWid):
    """ crapppy copy of scroll wid, allows for underlineing of specific chars
    Todo make less crapy
    """

    def setItems(self, itemList=None, itemFmt=None):

        itemList = self._items if itemList is None else itemList
        self._itemFmt = itemFmt
        super(ScrollWidU, self).setItems(itemList=itemList)
        if self._itemFmt is None:
            return

        hl = Color.HIGHLIGHT.pair if self.focus else Color.SELECTED.pair
        for i, thing in enumerate(itemList):
            color = hl if i == self._scrollIndex else Color.TEXT.pair
            self.addstr(i, 0, thing, itemFmt[i], color)

    def addstr(self, y, x, string, fmt, color):
        self.pad.move(y, x)
        cu = color | curses.A_UNDERLINE
        for ch, f in zip(list(string), list(fmt)):
            c = cu if f == '_' else color
            self.pad.addch(str(ch), c)

    def draw(self, onlyfocus=False):
        super(ScrollWidU, self).draw(onlyfocus=onlyfocus)
        if self._itemFmt is None:
            return
        if self.focus:
            color = Color.HIGHLIGHT.pair | curses.A_REVERSE
        else:
            color = Color.TEXT.pair
        # if self._visibleItems:
        string = self._visibleItems[self._scrollIndex]
        fmt = self._itemFmt[self._scrollIndex]
        self.addstr(self._scrollIndex, 0, string, fmt, color)

    def scroll(self, amount):
        super(ScrollWidU, self).scroll(amount)
        if self._itemFmt is None:
            return
        string = self._visibleItems[self._previousIndex]
        fmt = self._itemFmt[self._previousIndex]
        self.addstr(self._previousIndex, 0, string, fmt, Color.TEXT.pair)
        if self.focus:
            color = Color.HIGHLIGHT.pair | curses.A_REVERSE
        else:
            color = Color.SELECTED.pair | curses.A_REVERSE
        string = self._visibleItems[self._scrollIndex]
        fmt = self._itemFmt[self._scrollIndex]
        self.addstr(self._scrollIndex, 0, string, fmt, color)
        self.doRefresh()

    def processKeypress(self, ch):
        if ch in Keys.FIND:
            return
        super(ScrollWidU, self).processKeypress(ch)

class TextBox(Widget):

    def __init__(self, parent):

        self.parentWidget = parent
        self.parent = parent.getWindow()

        self._lastcursor = (0, 0)
        self._text = ''

        self.window = self.newwin()
        self.textpad = curses.textpad.Textbox(self.window)

    def getWindow(self):
        """ the thing a child will look to as parent """
        return self.window

    def draw(self):
        """ draw function here """
        y, x = self.parentPos()
        h, w = self.parentSize()

        self.window.resize(h, w)
        self.window.mvwin(y, x)

        wh, ww = self.window.getmaxyx()
        message = '< Enter Some Text >'
        self.window.addnstr(0, 1, message, ww - 1)

    def edit(self):

        if not self._text:
            self.window.erase()

        self.window.move(*self._lastcursor)
        setCursor(1)
        self.textpad.edit(self.validate)
        setCursor(0)

    def text(self):
        return self._text

    def validate(self, key):

        stopKey = ord(curses.ascii.ctrl('g'))

        if key == curses.ascii.ESC:
            self._lastcursor = self.window.getyx()
            self._text = ''
            return stopKey
        if key == Keys.KEY_ENTER:
            self._lastcursor = self.window.getyx()
            self._text = self.textpad.gather()
            return stopKey

        return key

    def doRefresh(self):
        """ noutrefresh-es go here"""
        self.window.noutrefresh()

class HLayout(Widget):

    def __init__(self, parent):

        self.parentWidget = parent
        self.parent = parent.getWindow()

        self.windows = []

    def addChild(self, child):

        window = self.newwin()
        self.windows.append(window)
        child.parent = window

    def getWindow(self):
        return self.parent

    def draw(self):
        """ draw function here """
        y, x = self.parentPos()
        h, w = self.parentSize()

        y+= 1

        winnum = len(self.windows)
        winw = w // winnum
        winh = h

        missingCols = w - (winnum * winw)

        for i, window in enumerate(self.windows):
            winx = x + winw * i
            if i + 1 == winnum:
                winw += missingCols
            window.resize(winh, winw)
            window.mvwin(y, winx)

    def doRefresh(self):
        """ noutrefresh-es go here"""

class StackedWidget(Widget):

    def __init__(self, parent):

        self.parentWidget = parent
        self.parent = parent.getWindow()
        self._currentIndex = 0

    def index(self):
        return self._currentIndex

    def currentWidget(self):
        return self._widgets[self._currentIndex]

    def setWidgets(self, widgets):
        self._widgets = widgets

    def setCurrent(self, index):

        if self._widgets and index < len(self._widgets):
            self._currentIndex = index
            self.draw()
            self.doRefresh()

    def getWindow(self):
        """ the thing a child will look to as parent """
        return self.parent

    def draw(self):
        """ draw function here """
        if self._widgets:
            self._widgets[self._currentIndex].draw()

    def doRefresh(self):
        """ noutrefresh-es go here"""
        if self._widgets:
            self._widgets[self._currentIndex].doRefresh()

    def processKeypress(self, ch):

        if self._widgets:
            self._widgets[self._currentIndex].processKeypress(ch)

    def mouseEvent(self, bstate, y, x, callback):
        if self._widgets:
            self._widgets[self._currentIndex].mouseEvent(
                bstate, y, x, callback)

# --------------------------------------------------------------------------- #
# - Popups                                                                 - #
# --------------------------------------------------------------------------- #

class PopupEnterText(Widget):

    def __init__(self, parent):
        self.parentWidget = parent
        self.parent = parent.getWindow()
        self.window = self.newwin()
        self.title = 'Filter Text'

        # popup
        self.popup = CSizeWid(self)
        self.dsw = DropShadowWid(self.popup)
        self.linePos = CSizeWid(self.dsw)
        self.tbox = TextBox(self.linePos)

    def execute(self):
        self.draw()
        self.doRefresh()

        # get text
        self.tbox.edit()
        return self.tbox.text()

    def getWindow(self):
        """ the thing a child will look to as parent """
        return self.parent

    def draw(self):
        """ draw function here """

        self.popup.targetHeight = 4
        self.dsw.title = self.title
        self.dsw.focus = True
        self.linePos.targetHeight = 1

        self.popup.draw()
        self.dsw.draw()
        self.linePos.draw()
        self.tbox.draw()

    def doRefresh(self):
        """ noutrefresh-es go here"""
        self.dsw.doRefresh()
        self.tbox.doRefresh()

class PopupOkCancel(Widget):

    def __init__(self, parent, title, cancelFirst=False):

        self.parentWidget = parent
        self.parent = parent.getWindow()
        self.window = curses.newwin(0, 0)
        self.helper = None
        self.title = title

        # popup
        self.popup = CSizeWid(self)
        self.popup.targetHeight = 5
        self.popup.targetWidth = len(title) + 4
        self.dsw = DropShadowWid(self.popup)
        self.scroll = ScrollWid(self.dsw)

        self.scroll.focus = True
        areas = ['Ok', 'Cancel']
        areas = reversed(areas) if cancelFirst else areas
        self.scroll.setItems(areas)

    def execute(self):
        # self.tbox.edit()

        # NOTE I may be able to replace BS with curses.erasechar()

        self.draw()
        self.doRefresh()
        curses.doupdate()

        # getch refreshes the window
        # this would clear the screen
        # workaround is a new dummy window
        # chwindow = curses.newwin(1, 1)
        # chwindow.keypad(1)

        while True:

            # less hacky but adds a square in the corner
            # ch = chwindow.getch()

            # I'll stick with the hack for now
            ch = self.getStdscreen().getch()
            self.scroll.processKeypress(ch)

            self.draw()
            self.doRefresh()

            if ch in Keys.ENTER:
                item = self.scroll.currentItem().strip()
                if not item or item.startswith('#'):
                    continue
                return item
            elif ch == Keys.KEY_RESIZE:
                return ''
            elif ch in Keys.CANCEL:
                return ''
            elif ch in Keys.DELETE:
                return ''
            elif ch == Keys.KEY_MOUSE:
                _id, x, y, z, bstate = curses.getmouse()
                self.scroll.mouseEvent(bstate, y, x, None)
                if bstate == curses.BUTTON1_DOUBLE_CLICKED:
                    curses.ungetch(Keys.ENTER[0])
                elif bstate == Keys.KEY_WHEEL_UP:
                    curses.ungetch(Keys.UP[0])
                elif bstate == Keys.KEY_WHEEL_DOWN:
                    curses.ungetch(Keys.DOWN[0])

            curses.doupdate()

    def draw(self):
        """ draw function here """

        self.dsw.title = self.title
        self.dsw.focus = True
        # self.linePos.targetHeight = 1

        self.popup.draw()
        self.dsw.draw()
        # self.linePos.draw()
        self.scroll.draw()

    def doRefresh(self):
        """ noutrefresh-es go here"""
        self.dsw.doRefresh()
        self.scroll.doRefresh()

class PopupTextWin(PopupOkCancel):

    def __init__(self, parent, text, h=45, w=160):

        self.parentWidget = parent
        self.parent = parent.getWindow()
        self.window = curses.newwin(0, 0)
        self.title = ''

        # popup
        self.popup = CSizeWid(self)
        self.popup.targetHeight = h
        self.popup.targetWidth = w
        self.dsw = DropShadowWid(self.popup)
        self.scroll = ScrollWid(self.dsw)
        self.scroll.setItems(text.strip().split('\n'))

    def execute(self):

        self.draw()
        self.doRefresh()
        curses.doupdate()
        while True:
            chwindow = curses.newwin(1, 1)
            ch = chwindow.getch()
            if self.processKeypress(ch):
                break
            self.draw()
            self.doRefresh()
            curses.doupdate()

    def processKeypress(self, ch):

        y, x = self.scroll.getWindow().getmaxyx()
        contentH, _ = self.scroll.pad.getmaxyx()

        if ch in Keys.UP:
            self.scroll.pageScroll(-1)
        elif ch in Keys.DOWN:
            self.scroll.pageScroll(1)
        elif ch in Keys.PAGE_UP:
            self.scroll.scroll(-y)
        elif ch in Keys.PAGE_DOWN:
            self.scroll.scroll(y)
        elif ch in Keys.TOP:
            self.scroll.scroll(-contentH)
        elif ch in Keys.BOTTOM:
            self.scroll.scroll(contentH)
        elif ch == Keys.KEY_MOUSE:
            _id, x, y, z, bstate = curses.getmouse()
            self.scroll.mouseEvent(bstate, y, x, None)
        elif ch == Keys.KEY_RESIZE:
            Color.BG.fillScreen(self.getStdscreen(), ' ')
            self.refreshTop()
        else:
            return True

    def draw(self):
        """ draw function here """

        self.dsw.title = self.title
        self.dsw.focus = True
        self.popup.draw()
        self.dsw.draw()
        self.scroll.draw()

    def doRefresh(self):
        """ noutrefresh-es go here"""
        self.popup.doRefresh()
        self.dsw.doRefresh()
        self.scroll.doRefresh()

# --------------------------------------------------------------------------- #
# - Windows                                                                 - #
# --------------------------------------------------------------------------- #

class GameWidget(Widget):

    def __init__(self, parent):

        self.parentWidget = parent
        self.parent = parent.getWindow()
        self.title = 'Paks'
        self.appVersionMode = False

        self._widgets = []
        self._focusGroups = []
        self._focusIndex = 0

        topGrp = BlankWid(parent)

        lShadow = FrameWid(parent)
        rShadow = FrameWid(parent)

        lShadow.title = 'Stuff'
        rShadow.title = 'Games'

        hlay = HLayout(topGrp)
        hlay.addChild(lShadow)
        hlay.addChild(rShadow)

        self.scroll1 = s1 = ScrollWid(lShadow)
        self.scroll2 = s2 = ScrollWid(rShadow)

        self.addWidget(topGrp)
        self.addWidget(hlay)

        self.addWidget(lShadow)
        self.addWidget(rShadow)

        self.addWidget(s1)
        self.addWidget(s2)

        self._focusGroups = [[lShadow, s1], [rShadow, s2]]

    def populate(self, items):

        # if not self.appVersionMode or not self.scroll1.currentItem():
            # self.scroll1.setItems(items)
            # return

        # currentItem = stripRmItmPrefix(self.scroll1.currentItem())
        # itemList = [stripRmItmPrefix(i) for i in self.scroll1.getItems(True)]

        # # Keep Index
        # cur = self.helper.getPakApp(self.scroll1.currentItem())
        # vis = [self.helper.getPakApp(i) for i in self.scroll1.getItems(True)]
        # if cur in vis:
            # index = vis.index(cur)
        # else:
            # index = 0

        self.scroll1.setItems(items)
        # self.scroll1.scroll(index)

    def addWidget(self, widget):
        self._widgets.append(widget)

    def draw(self):

        for i, group in enumerate(self._focusGroups):
            for w in group:
                if i == self._focusIndex:
                    w.focus = True
                else:
                    w.focus = False

        for widget in self._widgets:
            widget.draw()

    def focusOffset(self, offset):

        items = len(self._focusGroups)

        self._focusIndex += offset

        if self._focusIndex < 0:
            self._focusIndex = items - 1
        if self._focusIndex > items - 1:
            self._focusIndex = 0

        self.draw()
        self.doRefresh()

    def doRefresh(self):

        for widget in self._widgets:
            widget.doRefresh()

    def getCurrentPakApp(self):

        if self._focusIndex == 0:
            return None
        elif self._focusIndex == 1:
            return self.scroll2.currentItem()

    def processKeypress(self, ch):

        # send keypress to the section in focus
        if self._focusIndex == 0:
            self.scroll1.processKeypress(ch)
        elif self._focusIndex == 1:
            self.scroll2.processKeypress(ch)
        # elif self._focusIndex == 2:
            # if self.bottomWid.processKeypress(ch):
                # self.refreshTop()

        # move focus
        if ch in Keys.LEFT:
            self.focusOffset(-1)
        elif ch in Keys.RIGHT:
            self.focusOffset(1)

        # if the find key was hit stuff changed by now
        elif ch in Keys.FIND:
            self.draw()
            self.doRefresh()

        elif ch in Keys.ENTER:

            if self._focusIndex == 0:
                pak = self.scroll1.currentItem()
                if self.appVersionMode:
                    pak = 'SpecialPakName'
                self.scroll2.filterText = ''
                versions = 'this is a test'.split(' ')
                self.scroll2.setItems(versions)
                self.draw()
                self.doRefresh()
                if versions:
                    self.focusOffset(1)

            elif self._focusIndex == 1:
                for func in self._addVersionFuncs:
                    func(self.scroll2.currentItem())

        elif ch in Keys.DELETE:
            if self._focusIndex == 0:
                for func in self._delVersionFuncs:
                    func(self.scroll1.currentItem())

    def mouseEvent(self, bstate, y, x, callback):

        for i, widgets in enumerate(self._focusGroups):
            frame, scroll = widgets
            if frame.getWindow().enclose(y, x):
                self._focusIndex = i
                self.draw()
                self.doRefresh()
            if scroll.getWindow().enclose(y, x):
                scroll.mouseEvent(bstate, y, x, callback)

class HelpWin(Widget):

    def __init__(self, parent):

        self.parentWidget = parent
        self.parent = parent.getWindow()
        # self.window = FrameWid(self)
        self.window = self.newwin()
        self.title = 'Help'

        self.frame = FrameWid(self)

        # Color.WINDOW_OFF.fillScreen(self.window)

        self.scrollArea = ScrollWid(self.frame)
        self.scrollArea.pageMode = True

    def getWindow(self):
        return self.window

    def processKeypress(self, ch):
        self.scrollArea.processKeypress(ch)
        self.scrollArea.doRefresh()

    def draw(self):
        """ draw function here """
        y, x = self.parentPos()
        h, w = self.parentSize()

        self.window.resize(h - 1, w)
        self.window.mvwin(y + 1, x)
        self.window.border(*BORDER_ARGS)

        wh, ww = self.window.getmaxyx()
        # message = self.title or 'Example Widget'
        # self.window.addnstr(0, 1, message, ww - 1)

        self.frame.title = self.title
        self.frame.draw()

        self.scrollArea.draw()
        self.scrollArea.setItems(HELP.strip().split('\n'))

    def doRefresh(self):
        """ noutrefresh-es go here"""
        # self.window.noutrefresh()
        self.frame.doRefresh()
        self.scrollArea.doRefresh()

# --------------------------------------------------------------------------- #
# - Main                                                                    - #
# --------------------------------------------------------------------------- #

class MainWindow(object):

    def __init__(self, stdscr):

        self._widgets = []
        self._mouseWidgets = []
        self._run = True
        self._bottomFocus = False
        self.stdscr = stdscr
        self.stdscr.nodelay(False)

        appNames = 'app names would go here'.split(' ')

        marg = CSizeWid(self)
        marg.targetHeight = WINDOW_SIZE[0]
        marg.targetWidth = WINDOW_SIZE[1]
        marg.show = False

        dsw = DropShadowWid(marg)
        dsw.dropShadowOutside = True
        dsw.title = 'Oz Wizard'

        # Help
        self.helpWin = HelpWin(dsw)

        # All
        self.pakWin = GameWidget(dsw)
        self.pakWin.title = 'All Paks'
        self.pakWin.populate(appNames)

        windows = [
            self.helpWin,
            self.pakWin,
        ]
        self.stack = StackedWidget(dsw)
        self.stack.setWidgets(windows)

        self.stack._currentIndex = 1

        self.tabs = TabBar(self.stack)
        self.tabs.items = ['F1:Help', 'F2:All']
        self.tabs.tabIndex = 1

        self.addWidget(marg)
        self.addWidget(dsw)
        self.addWidget(self.stack)
        self.addWidget(self.tabs)

    def addPak(self, pak):
        pass

    def removePak(self, pak):
        pass

    def getWindow(self):
        return self.stdscr

    def addWidget(self, widget):
        self._widgets.append(widget)

    def close(self):
        self._run = False

    def draw(self, refresh=False, erase=False):

        # no sense in taking down the whole
        # application beacuse of a size error
        try:
            if erase:
                self.stdscr.erase()
            for widget in self._widgets:
                widget.draw()
            if refresh:
                self.doRefresh()
        except curses.error as e:
            tb = traceback.format_exc()
            Echo(tb)

    def doRefresh(self):

        self.stdscr.noutrefresh()
        for widget in self._widgets:
            widget.doRefresh()

    def setPage(self, index):
        self.stdscr.erase()
        self.stack.setCurrent(index)
        self.tabs.tabIndex = index
        self.draw(refresh=True)

    def mainLoop(self):
        """ to check for keys we must ignore catch key errors """

        stdscr = self.stdscr
        Color.BG.fillScreen(self.stdscr, ' ')

        self.draw()
        self.doRefresh()
        curses.doupdate()

        while self._run:
            ch = self.stdscr.getch()
            ch = self.processKeypress(ch)
            self.stack.processKeypress(ch)

            curses.doupdate()

    def _popupError(self, e):

        msg = '%s: %s' % (e.__class__.__name__, e)
        Echo(msg)
        h = msg.count('\n') + 5
        w = max([len(l) for l in msg.split('\n')]) + 4
        popup = PopupTextWin(self, msg, h, w)
        popup.title = 'Error'
        popup.execute()
        self.draw(refresh=True, erase=True)

    def viewPakDump(self):

        json = HELP
        popup = PopupTextWin(self, json)
        popup.title = 'Pak Dump %s ' % pak
        popup.execute()
        self.draw(refresh=True, erase=True)

    @staticmethod
    def _stopCurses():
        curses.echo()
        curses.nocbreak()
        curses.endwin()

    @staticmethod
    def _startCurses():
        curses.noecho()
        curses.cbreak()

    def editPakInEditor(self):

        return

        # - Refresh Screen ----------------------------------------------------
        self.draw(refresh=True, erase=True)

    def processKeypress(self, ch):

        if ch in Keys.QUIT:
            self.close()

        # elif ch in Keys.EXECUTE:
            # self.pakWin.bottomWid._popupChooseProgram()
            # self.draw(refresh=True)

        # elif ch in Keys.SET_MODE:
            # self.pakWin.bottomWid._popupChooseOz()
            # self.draw(refresh=True)

        # elif ch in Keys.CLEAR_SCREEN:
            # self.stdscr.clear()

        elif ch in Keys.TAB_HELP:
            self.setPage(0)

        elif ch in Keys.TAB_CURRENT:
            self.setPage(1)

        elif ch in Keys.EDIT_PAK:
            self.editPakInEditor()

        elif ch in Keys.TAB_PREV:
            i = self.tabs.tabIndex
            i -= 1
            i = len(self.tabs.items) - 1 if i < 0 else i
            self.setPage(i)

        elif ch in Keys.TAB_NEXT:
            i = self.tabs.tabIndex
            i += 1
            i = 0 if len(self.tabs.items) - 1 < i else i
            self.setPage(i)

        elif ch == Keys.KEY_RESIZE:
            self.stdscr.clear()
            self.draw(refresh=True)

        elif ch == Keys.KEY_MOUSE:
            _id, x, y, z, bstate = curses.getmouse()

            if bstate == Keys.KEY_WHEEL_UP:
                return Keys.UP[0]

            elif bstate == Keys.KEY_WHEEL_DOWN:
                return Keys.DOWN[0]

            for widget, callback in self._mouseWidgets:
                widget.mouseEvent(bstate, y, x, callback)
            if bstate == curses.BUTTON1_DOUBLE_CLICKED:
                curses.ungetch(Keys.ENTER[0])

        return ch

    @classmethod
    def appStart(cls):
        """ modified curses.wrapper
        """
        msg = None
        try:
            Echo('Started', datetime.datetime.now())
            # shorten escape key delay
            os.environ.setdefault('ESCDELAY', '25')

            # Initialize curses
            stdscr = curses.initscr()
            curses.noecho()
            curses.cbreak()
            # curses.mouseinterval(600)
            # needed for arrow keys
            stdscr.keypad(1)
            setCursor(0)
            curses.mousemask(
                curses.ALL_MOUSE_EVENTS |
                curses.REPORT_MOUSE_POSITION)

            Color.initPairs()

            app = cls(stdscr)
            app.mainLoop()
            msg = 'Canceled'

        except Quit as e:
            msg = e

        except Exception as e:
            tb = traceback.format_exc()
            Echo(tb)
            msg = tb

        finally:
            # Set everything back to normal
            if 'stdscr' in locals():
                stdscr.keypad(0)
                curses.echo()
                curses.nocbreak()
                curses.endwin()

        if msg:
            Echo(msg)
            print msg

if __name__ == '__main__':
    # print "\033k{}\033\\".format('ozz')
    try:
        MainWindow.appStart()
    except KeyboardInterrupt:
        print 'Canceled'

