# Copyright (C) 2001-2006 Python Software Foundation
# Author: Keith Dart
# Contact: email-sig@python.org
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

"""Class representing application/* type MIME documents."""

__all__ = ["MIMEApplication"]

from email import encoders
from email.mime.nonmultipart import MIMENonMultipart


class MIMEApplication(MIMENonMultipart):
    """Class for generating application/* MIME documents."""

    def __init__(self, _data, _subtype='octet-stream',
                 _encoder=encoders.encode_base64, **_params):
        """Create an application/* type MIME document.

        _data is a string containing the raw applicatoin data.

        _subtype is the MIME content type subtype, defaulting to
        'octet-stream'.

        _encoder is a function which will perform the actual encoding for
        transport of the application data, defaulting to base64 encoding.

        Any additional keyword arguments are passed to the base class
        constructor, which turns them into parameters on the Content-Type
        header.
        """
        if _subtype is None:
            raise TypeError('Invalid application MIME subtype')
        MIMENonMultipart.__init__(self, 'application', _subtype, **_params)
        self.set_payload(_data)
        _encoder(self)
