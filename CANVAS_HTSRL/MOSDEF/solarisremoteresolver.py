#! /usr/bin/env python

"""
the solaris remote resolver. A kind of combination of libc and a few other things...

TODO:

Either completely remove this file by refactoring in some way or convert all
assembly into MOSDEF-C or (most likely option) convert the assembly that is
sparc into x86/MOSDEF-C when self.arch=="X86"

"""

from remoteresolver import remoteresolver
import threading

class solarisremoteresolver(remoteresolver):
    
    def __init__(self, proc, version):
        remoteresolver.__init__(self, 'Solaris', proc, version)
        self.compilelock=threading.RLock()
        self.localcache={}
    
    def initLocalFunctions(self):
        print "XXX: moved all remote resolver local function inits to MOSDEF/MOSDEFLibc/Solaris.py !!!"
        print "XXX: don't need this call to initLocalFunctions ... (platform)"
                
class sparcsolarisremoteresolver(solarisremoteresolver):
    def __init__(self, proc = "sparc", version = "2.7"):
        solarisremoteresolver.__init__(self, proc, version)
        solarisremoteresolver.initLocalFunctions(self)
            
    def initLocalFunctions(self):
        print "XXX: moved all remote resolver local function inits to MOSDEF/MOSDEFLibc/Solaris.py !!!"
        print "XXX: don't need this call to initLocalFunctions ... (sparc)"

class x86solarisremoteresolver(solarisremoteresolver):
    def __init__(self, proc = "x86", version = "2.10"):
        solarisremoteresolver.__init__(self, proc, version)
        solarisremoteresolver.initLocalFunctions(self)

    def initLocalFunctions(self):
        print "XXX: moved all remote resolver local function inits to MOSDEF/MOSDEFLibc/Solaris.py !!!"
        print "XXX: don't need this call to initLocalFunctions ... (intel)"

x86solarisremoteresolver

