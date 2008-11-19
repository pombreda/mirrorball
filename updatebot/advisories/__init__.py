#
# Copyright (c) 2008 rPath, Inc.
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

"""
Top level advisories module.
"""

import logging
from imputil import imp

log = logging.getLogger('updatebot.advisories')

class InvalidBackendError(Exception):
    pass

__supported_backends = ('sles', 'centos')

def __getBackend(backend):
    if backend not in __supported_backends:
        raise InvalidBackendError('%s is not a supported backend, please '
            'choose from %s' % (backend, ','.join(__supported_backends)))

    try:
        updatebotPath = [imp.find_module('updatebot')[1], ]
        advisoriesPath = [imp.find_module('advisories', updatebotPath)[1], ]
        mod = imp.find_module(backend, advisoriesPath)
        loaded = imp.load_module(backend, mod[0], mod[1], mod[2])
        return loaded
    except ImportError, e:
        raise InvalidBackendError('Could not load %s backend: %s'
                                  % (backend, e))

def Advisor(cfg, pkgSource, backend):
    module = __getBackend(backend)
    obj = module.Advisor(cfg, pkgSource)
    return obj