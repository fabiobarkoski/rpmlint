#############################################################################
# File		: Pkg.py
# Package	: rpmlint
# Author	: Frederic Lepied
# Created on	: Tue Sep 28 07:18:06 1999
# Version	: $Id$
# Purpose	: provide an API to handle a rpm package either by accessing
#		the rpm file or by accessing the files contained inside.
#############################################################################

import os
import rpm
import os.path
import stat
import commands
import re
import string
import types

RPMFILE_CONFIG=(1 << 0)
RPMFILE_DOC=(1 << 1)
RPMFILE_DONOTUSE=(1 << 2)
RPMFILE_MISSINGOK=(1 << 3)
RPMFILE_NOREPLACE=(1 << 4)
RPMFILE_SPECFILE=(1 << 5)
RPMFILE_GHOST=(1 << 6)
RPMFILE_LICENSE=(1 << 7)
RPMFILE_README=(1 << 8)

# check if we use a rpm version compatible with 3.0.4
try:
    if rpm.RPMTAG_OLDFILENAMES:
        v304=1
except AttributeError:
    v304=0

def grep(regex, filename):
    fd=open(filename, "r")
    ret=0
    if fd:
        reg=re.compile(regex)
        
        for line in fd.readlines():
            if reg.search(line):
                ret=1
                break
        fd.close()
    else:
        print "unable to open", f
    return ret

class Pkg:
    file_regex=re.compile("\.([^:]+):\s+(.*)")

    def __init__(self, filename, dirname):
	self.filename=filename
	self.extracted=0
	self.dirname=dirname
	self.file_info=None
	self._config_files=None
	self._doc_files=None
	self._ghost_files=None
	self._files=None
	self.required=None
        
	# Create a package object from the file name
	fd=os.open(filename, os.O_RDONLY)
	(self.header, self.is_source)=rpm.headerFromPackage(fd)
	os.close(fd)

	self.name=self.header[rpm.RPMTAG_NAME]

    # Return true is the package is a source package
    def isSource(self):
	return self.is_source

    # access the tags like an array
    def __getitem__(self, key):
	return self.header[key]

    # return the name of the directory where the package is extracted
    def dirName(self):
	if not self.extracted:
	    self._extract()
	return self.dirname

    # handle the extract phasis
    def _extract(self):
	s=os.stat(self.dirname)
        if not stat.S_ISDIR(s[stat.ST_MODE]):
            print "unable to access dir", self.dirname
        else:
            self.dirname = "%s/%s.%d" % (self.dirname, os.path.basename(self.filename), os.getpid())
            os.mkdir(self.dirname)
            str="rpm2cpio %s | (cd %s; cpio -id)" % (self.filename, self.dirname)
            cmd=commands.getstatusoutput(str)
	    self.extracted=1

    # return the array of info returned by the file command on each file
    def getFilesInfo(self):
	if self.file_info == None:
	    self.file_info=[]
	    lines=commands.getoutput("cd %s; find . -type f -print0 | xargs -0r file" % (self.dirName()))
	    lines=string.split(lines, "\n")
	    for l in lines:
		#print l
		res=Pkg.file_regex.search(l)
		if res:
		    self.file_info.append([res.group(1), res.group(2)])
	    #print self.file_info
	return self.file_info

    # remove the extracted files from the package
    def cleanup(self):
	if self.extracted:
	    commands.getstatusoutput("chmod -R +X " + self.dirname)
	    commands.getstatusoutput("rm -rf " + self.dirname)

    # return the associative array indexed on file names with
    # the values as: (file perm, file owner, file group, file link to)
    def files(self):
	if self._files != None:
	    return self._files
	self._gatherFilesInfo()
	return self._files

    # return the list of config files
    def configFiles(self):
	if self._config_files != None:
	    return self._config_files
	self._gatherFilesInfo()
	return self._config_files

    # return the list of documentation files
    def docFiles(self):
	if self._doc_files != None:
	    return self._doc_files
	self._gatherFilesInfo()
	return self._doc_files

    # return the list of ghost files
    def ghostFiles(self):
	if self._ghost_files != None:
	    return self._ghost_files
	self._gatherFilesInfo()
	return self._ghost_files

    # extract information about the files
    def _gatherFilesInfo(self):
        global v304
        
	self._config_files=[]
	self._doc_files=[]
	self._ghost_files=[]
	self._files={}
	flags=self.header[rpm.RPMTAG_FILEFLAGS]
	modes=self.header[rpm.RPMTAG_FILEMODES]
	users=self.header[rpm.RPMTAG_FILEUSERNAME]
	groups=self.header[rpm.RPMTAG_FILEGROUPNAME]
	links=self.header[rpm.RPMTAG_FILELINKTOS]
        # Get files according to rpm version
        if v304:
            files=self.header[rpm.RPMTAG_OLDFILENAMES]
            if files == None:
                basenames=self.header[rpm.RPMTAG_BASENAMES]
                if basenames:
                    dirnames=self.header[rpm.RPMTAG_DIRNAMES]
                    dirindexes=self.header[rpm.RPMTAG_DIRINDEXES]
                    files=[]
                    # The rpmlib or the python module doesn't report a list for RPMTAG_DIRINDEXES
                    # if the list has one element...
                    if type(dirindexes) == types.IntType:
                        files.append(dirnames[dirindexes] + basenames[0])
                    else:
                        for idx in range(0, len(dirindexes)):
                            files.append(dirnames[dirindexes[idx]] + basenames[idx])
        else:
            files=self.header[rpm.RPMTAG_FILENAMES]

	if files:
	    for idx in range(0, len(files)):
		if flags[idx] & RPMFILE_CONFIG:
		    self._config_files.append(files[idx])
		elif flags[idx] & RPMFILE_DOC:
		    self._doc_files.append(files[idx])
		elif flags[idx] & RPMFILE_GHOST:
		    self._ghost_files.append(files[idx])
		self._files[files[idx]]=(modes[idx], users[idx],
					 groups[idx], links[idx])

    # API to access dependency information
    def requires(self):
        self._gatherDepInfo()
        return self._requires
    
    def prereq(self):
        self._gatherDepInfo()
        return self._prereq

    def conflicts(self):
        self._gatherDepInfo()
        return self._conflicts
        
    def provides(self):
        self._gatherDepInfo()
        return self._provides

    # internal function to gather dependency info used by the above ones
    def _gatherDepInfo(self):
        if self.required == None:
            self._requires = []
            self._prereq = []
            self._provides = []
            self._conflicts = []
            
            names = self.header[rpm.RPMTAG_REQUIRENAME]
            versions = self.header[rpm.RPMTAG_REQUIREVERSION]
            flags = self.header[rpm.RPMTAG_REQUIREFLAGS]
            if versions:
                # workaroung buggy rpm python module that doesn't return a list
                if type(flags) != types.ListType:
                    flags=[flags]
                for loop in range(len(versions)):
                    if flags[loop] & rpm.RPMSENSE_PREREQ:
                        self._prereq.append((names[loop], versions[loop], flags[loop] & (not rpm.RPMSENSE_PREREQ)))
                    else:
                        self._requires.append((names[loop], versions[loop], flags[loop]))
                        
            names = self.header[rpm.RPMTAG_CONFLICTNAME]
            versions = self.header[rpm.RPMTAG_CONFLICTVERSION]
            flags = self.header[rpm.RPMTAG_CONFLICTFLAGS]
            if versions:
                # workaroung buggy rpm python module that doesn't return a list
                if type(flags) != types.ListType:
                    flags=[flags]
                for loop in range(len(versions)):
                    self._conflicts.append((names[loop], versions[loop], flags[loop]))
                    
            names = self.header[rpm.RPMTAG_PROVIDENAME]
            versions = self.header[rpm.RPMTAG_PROVIDEVERSION]
            flags = self.header[rpm.RPMTAG_PROVIDEFLAGS]
            if versions:
                # workaroung buggy rpm python module that doesn't return a list
                if type(flags) != types.ListType:
                    flags=[flags]
                for loop in range(len(versions)):
                    self._provides.append((names[loop], versions[loop], flags[loop]))
            
if __name__ == '__main__':
    import sys
    for p in sys.argv[1:]:
        pkg=Pkg(sys.argv[1], "/tmp")
        print "Requires:", pkg.requires()
        print "Prereq:", pkg.prereq()
        print "Conflicts:", pkg.conflicts()
        print "Provides:", pkg.provides()
        pkg.cleanup()
    
# Pkg.py ends here
