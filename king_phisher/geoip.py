#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  king_phisher/geoip.py
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are
#  met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following disclaimer
#    in the documentation and/or other materials provided with the
#    distribution.
#  * Neither the name of the project nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
#  "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
#  LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
#  A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
#  OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
#  SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
#  LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
#  DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
#  THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
#  OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

import collections
import gzip
import ipaddress
import logging
import os
import shutil
import sys
import tempfile
import threading

import geoip2.database

if sys.version_info[0] < 3:
	import urllib
	urllib.request = urllib
else:
	import urllib.request

__all__ = ['init_database', 'lookup', 'GeoLocation']

DB_DOWNLOAD_URL = 'http://geolite.maxmind.com/download/geoip/database/GeoLite2-City.mmdb.gz'
"""The URL from which the GeoLite2 City database can be downloaded from."""
DB_RESULT_FIELDS = ('city', 'continent', 'coordinates', 'country', 'postal_code', 'time_zone')
"""A tuple listing the fields that are required in database results."""

_geoip_db = None
_geoip_db_lock = threading.RLock()
logger = logging.getLogger('KingPhisher.geoip')

def download_geolite2_city_db(dest):
	"""
	Download the GeoLite2 database, decompress it, and save it to disk.

	:param str dest: The file path to save the database to.
	"""
	url_h = urllib.request.urlopen(DB_DOWNLOAD_URL)
	tfile = tempfile.mkstemp()
	os.close(tfile[0])
	tfile = tfile[1]
	try:
		with open(tfile, 'wb') as file_h:
			shutil.copyfileobj(url_h, file_h)
		with open(dest, 'wb') as file_h:
			shutil.copyfileobj(gzip.GzipFile(tfile, mode='rb'), file_h)
	finally:
		url_h.close()
		os.remove(tfile)
	return os.stat(dest).st_size

def init_database(database_file):
	"""
	Create and initialize the GeoLite2 database engine. This must be done before
	classes and functions in this module attempt to look up results. If the
	specified database file does not exist, a new copy will be downloaded.

	:param str database_file: The GeoLite2 database file to use.
	:return: The initialized GeoLite2 database object.
	:rtype: :py:class:`geoip2.database.Reader`
	"""
	global _geoip_db
	if not os.path.isfile(database_file):
		logger.warning('the specified geoip database does not exist, downloading a new copy')
		download_geolite2_city_db(database_file)
		os.chmod(database_file, 0644)
	_geoip_db = geoip2.database.Reader(database_file)
	metadata = _geoip_db.metadata()
	if not metadata.database_type == 'GeoLite2-City':
		raise ValueError('the connected database is not a GeoLite2-City database')
	return _geoip_db

def lookup(ip, lang='en'):
	"""
	Lookup the geo location information for the specified IP from the configured
	GeoLite2 City database.

	:param str ip: The IP address to look up the information for.
	:param str lang: The language to prefer for regional names.
	:return: The geo location information as a dict. The keys are the values of
		:py:data:`.DB_RESULT_FIELDS`.
	:rtype: dict
	"""
	global _geoip_db
	if not _geoip_db:
		raise RuntimeError('the geoip database has not been initialized yet')
	lang = (lang or 'en')
	if isinstance(ip, str):
		ip = ipaddress.ip_address(ip)
	if isinstance(ip, ipaddress.IPv6Address):
		raise TypeError('ipv6 addresses are not supported at this time')
	if ip.is_loopback or ip.is_private:
		raise RuntimeError('the specified IP address is not a public IP address')
	with _geoip_db_lock:
		city = _geoip_db.city(str(ip))
	result = {}
	result['city'] = city.city.names.get(lang)
	result['continent'] = city.continent.names.get(lang)
	result['coordinates'] = (city.location.latitude, city.location.longitude)
	result['country'] = city.country.names.get(lang)
	result['postal_code'] = city.postal.code
	result['time_zone'] = city.location.time_zone
	return result

Coordinates = collections.namedtuple('Coordinates', ['latitude', 'longitude'])

class GeoLocation(object):
	"""
	The geographic location information for a given IP address.
	"""
	def __init__(self, ip, lang='en', result=None):
		"""
		:param str ip: The IP address to look up geographic location data for.
		:param str lang: The language to prefer for regional names.
		:param dict result: A raw query result from a previous call to :py:func:`.lookup`.
		"""
		if isinstance(ip, str):
			ip = ipaddress.ip_address(ip)
		if not result:
			result = lookup(ip, lang=lang)
		self.ip_address = ip
		"""The :py:class:`~ipaddress.IPv4Address` which this geographc location data describes."""
		for field in DB_RESULT_FIELDS:
			if not field in result:
				raise RuntimeError('the retrieved information is missing required data')
			if field in ('coordinates',):
				continue
			setattr(self, field, result[field])
		self.coordinates = Coordinates(latitude=result['coordinates'][0], longitude=result['coordinates'][1])
		self.raw = result

	def __repr__(self):
		return "<{0} ip={1} >".format(self.__class__.__name__, self.ip_address)

	def __str__(self):
		if self.city:
			return "{0}, {1}".format(self.city, self.country)
		return self.country
