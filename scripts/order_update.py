#!/usr/bin/python
#
# Copyright (c) 2009-2010 rPath, Inc.
#
# This program is distributed under the terms of the Common Public License,
# version 1.0. A copy of this license should have been distributed with this
# source file in a file called LICENSE. If it is not present, the license
# is always available at http://www.rpath.com/permanent/licenses/CPL-1.0.
#
# This program is distributed in the hope that it will be useful, but
# without any warranty; without even the implied warranty of merchantability
# or fitness for a particular purpose. See the Common Public License for
# full details.
#

import os
import sys
import logging

mirrorballDir = os.path.abspath('../')
sys.path.insert(0, mirrorballDir)

if 'CONARY_PATH' in os.environ:
    sys.path.insert(0, os.environ['CONARY_PATH'])

import conary
import updatebot

print >>sys.stderr, 'using conary from', os.path.dirname(conary.__file__)
print >>sys.stderr, 'using updatebot from', os.path.dirname(updatebot.__file__)

from conary.lib import util
sys.excepthook = util.genExcepthook()

from updatebot import config
from updatebot import ordered
from updatebot import log as logSetup

logSetup.addRootLogger()
log = logging.getLogger('script')

def usage():
    print 'usage: %s <platform>' % sys.argv[0]
    sys.exit(1)

platform = sys.argv[1]
if platform not in os.listdir(mirrorballDir + '/config'):
    usage()

restoreFile=None
if len(sys.argv) > 2:
    restoreFile = sys.argv[2]

confDir = mirrorballDir + '/config/' + platform

cfg = config.UpdateBotConfig()
cfg.read(confDir + '/updatebotrc')

fltr = None

if cfg.platformName == 'rhel':
    import rhnmirror

    mcfg = rhnmirror.MirrorConfig()
    mcfg.read(confDir + '/erratarc')

    errata = rhnmirror.Errata(mcfg)

    bot = ordered.Bot(cfg, errata)

else:
    bot = ordered.Bot(cfg, None)

    if cfg.platformName == 'sles':
        from errata.sles import AdvisoryManager as Errata

    elif cfg.platformName == 'centos':
        from errata.centos import AdvisoryManager as Errata

    else:
        raise RuntimeError, 'no errata source found for %s' % cfg.platformName

    errata = Errata(bot._pkgSource)
    bot._errata._errata = errata

pkgMap = bot.update(fltr=fltr, restoreFile=restoreFile)

import epdb; epdb.st()
