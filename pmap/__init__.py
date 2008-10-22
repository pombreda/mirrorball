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
PMAP - PiperMail Archive Parser

Parse advisories from pipermail archives.
"""

from imputil import imp

__all__ = ('InvalidBackendError', 'parse')
__supported_backends = ('ubuntu', 'centos')

class InvalidBackendError(Exception):
    pass

def __getBackend(backend):
    if backend not in __supported_backends:
        raise InvalidBackendError('%s is not a supported backend, please '
            'choose from %s' % (backend, ','.join(__supported_backends)))

    try:
        path = [imp.find_module('pmap')[1], ]
        mod = imp.find_module(backend, path)
        loaded = imp.load_module(backend, mod[0], mod[1], mod[2])
        return loaded
    except ImportError, e:
        raise InvalidBackendError('Could not load %s backend: %s' % (backend, e))

def parse(url, backend='ubuntu'):
    backend = __getBackend(backend)
    parser = backend.Parser()
    return parser.parse(url)
