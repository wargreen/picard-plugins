# -*- coding: utf-8 -*-

PLUGIN_NAME = "Generate Cuesheet"
PLUGIN_AUTHOR = "Lukáš Lalinský, Sambhav Kothari"
PLUGIN_DESCRIPTION = "Generate cuesheet (.cue file) from an album."
PLUGIN_VERSION = "1.2.1"
PLUGIN_API_VERSIONS = ["2.0"]


import os.path
import re
from PyQt5 import QtCore, QtWidgets
from picard.util import find_existing_path, encode_filename
from picard.ui.itemviews import BaseAction, register_album_action


_whitespace_re = re.compile(r'\s', re.UNICODE)
_split_re = re.compile(r'\s*("[^"]*"|[^ ]+)\s*', re.UNICODE)


def msfToMs(msf):
    msf = msf.split(":")
    return ((int(msf[0]) * 60 + int(msf[1])) * 75 + int(msf[2])) * 1000 / 75


class CuesheetTrack(list):

    def __init__(self, cuesheet, index):
        list.__init__(self)
        self.cuesheet = cuesheet
        self.index = index

    def set(self, *args):
        self.append(args)

    def find(self, prefix):
        return [i for i in self if tuple(i[:len(prefix)]) == tuple(prefix)]

    def getTrackNumber(self):
        return self.index

    def getLength(self):
        try:
            nextTrack = self.cuesheet.tracks[self.index + 1]
            index0 = self.find(("INDEX", "01"))
            index1 = nextTrack.find(("INDEX", "01"))
            return msfToMs(index1[0][2]) - msfToMs(index0[0][2])
        except IndexError:
            return 0

    def getField(self, prefix):
        try:
            return self.find(prefix)[0][len(prefix)]
        except IndexError:
            return ""

    def getArtist(self):
        return self.getField(("PERFORMER",))

    def getTitle(self):
        return self.getField(("TITLE",))

    def setArtist(self, artist):
        found = False
        for item in self:
            if item[0] == "PERFORMER":
                if not found:
                    item[1] = artist
                    found = True
                else:
                    del item
        if not found:
            self.append(("PERFORMER", artist))

    artist = property(getArtist, setArtist)


class Cuesheet(object):

    def __init__(self, filename):
        self.filename = filename
        self.tracks = []

    def read(self):
        with open(encode_filename(self.filename)) as f:
            self.parse(f.readlines())

    def unquote(self, string):
        if string.startswith('"'):
            if string.endswith('"'):
                return string[1:-1]
            else:
                return string[1:]
        return string

    def quote(self, string):
        if _whitespace_re.search(string):
            return '"' + string.replace('"', '\'') + '"'
        return string

    def parse(self, lines):
        track = CuesheetTrack(self, 0)
        self.tracks = [track]
        isUnicode = False
        for line in lines:
            # remove BOM
            if line.startswith('\xfe\xff'):
                isUnicode = True
                line = line[1:]
            # decode to unicode string
            line = line.strip()
            if isUnicode:
                line = line.decode('UTF-8', 'replace')
            else:
                line = line.decode('ISO-8859-1', 'replace')
            # parse the line
            split = [self.unquote(s) for s in _split_re.findall(line)]
            keyword = split[0].upper()
            if keyword == 'TRACK':
                trackNum = int(split[1])
                track = CuesheetTrack(self, trackNum)
                self.tracks.append(track)
            track.append(split)

    def write(self):
        lines = []
        for track in self.tracks:
            num = track.index
            for line in track:
                indent = 0
                if num > 0:
                    if line[0] == "TRACK":
                        indent = 2
                    elif line[0] != "FILE":
                        indent = 4
                line2 = " ".join([self.quote(s) for s in line])
                line2 = " " * indent + line2 + "\n"
                lines.append(line2.encode("UTF-8"))
        with open(encode_filename(self.filename), "wb") as f:
            f.writelines(lines)


class GenerateCuesheet(BaseAction):
    NAME = "Generate &Cuesheet..."

    def callback(self, objs):
        album = objs[0]
        current_directory = self.config.persist["current_directory"] or QtCore.QDir.homePath()
        current_directory = find_existing_path(string_(current_directory))
        filename, selected_format = QtWidgets.QFileDialog.getSaveFileName(
            None, "", current_directory, "Cuesheet (*.cue)")
        if filename:
            filename = string_(filename)
            cuesheet = Cuesheet(filename)
            #try: cuesheet.read()
            #except IOError: pass
            while len(cuesheet.tracks) <= len(album.tracks):
                track = CuesheetTrack(cuesheet, len(cuesheet.tracks))
                cuesheet.tracks.append(track)
            #if len(cuesheet.tracks) > len(album.tracks) - 1:
            #    cuesheet.tracks = cuesheet.tracks[0:len(album.tracks)+1]

            t = cuesheet.tracks[0]
            t.set("PERFORMER", album.metadata["albumartist"])
            t.set("TITLE", album.metadata["album"])
            t.set("REM", "MUSICBRAINZ_ALBUM_ID", album.metadata["musicbrainz_albumid"])
            t.set("REM", "MUSICBRAINZ_ALBUM_ARTIST_ID", album.metadata["musicbrainz_albumartistid"])
            if "date" in album.metadata:
                t.set("REM", "DATE", album.metadata["date"])
            index = 0.0
            for i, track in enumerate(album.tracks):
                mm = index / 60.0
                ss = (mm - int(mm)) * 60.0
                ff = (ss - int(ss)) * 75.0
                index += track.metadata.length / 1000.0
                t = cuesheet.tracks[i + 1]
                t.set("TRACK", "%02d" % (i + 1), "AUDIO")
                t.set("PERFORMER", track.metadata["artist"])
                t.set("TITLE", track.metadata["title"])
                t.set("REM", "MUSICBRAINZ_TRACK_ID", track.metadata["musicbrainz_trackid"])
                t.set("REM", "MUSICBRAINZ_ARTIST_ID", track.metadata["musicbrainz_artistid"])
                t.set("INDEX", "01", "%02d:%02d:%02d" % (mm, ss, ff))
                for file in track.linked_files:
                    audio_filename = file.filename
                    extension = audio_filename.split(".")[-1].lower()
                    if os.path.dirname(filename) == os.path.dirname(audio_filename):
                        audio_filename = os.path.basename(audio_filename)
                    if extension in ["mp3", "mp2", "m2a"]:
                        file_type = "MP3"
                    elif extension in ["aiff", "aif", "aifc"]:
                        file_type = "AIFF"
                    else:
                        file_type = "WAVE"
                    cuesheet.tracks[i].set("FILE", audio_filename, file_type)

            cuesheet.write()


action = GenerateCuesheet()
register_album_action(action)
