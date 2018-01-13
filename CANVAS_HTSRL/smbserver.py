#! /usr/bin/env python

from exploitutils import *
import socket
import time
from msrpc import recvnetbios_server
from msrpc import netbios
from msrpc import read_unicode_string
import struct
import random


#####################################################################
NETBIOS_SESSION_REQUEST=0x81
SMB_TREE_CONNECT=0x70
SMB_NEGOTIATE_PROTOCOL=0x72
SMB_SESSION_SETUP_ANDX=0x73
SMB_TREE_CONNECT_ANDX=0x75
SMB_CHECK_DIRECTORY=0x10
SMB_ECHO_REQUEST=0x2b
SMB_SUCCESS=0
SMB_CREATE_ANDX=0xa2
SMB_READ_ANDX=0x2e
SMB_CLOSE=0x4
SMB_TREE_DISCONNECT=0x71
#SMB_QUERY_FILE_INFORMATION=0xff #???
SMB_TRANS2=0x32


STATUS_NOTIFY_ENUM_DIR=0x10c
SMB_FAIL=0xC0000001L #unsuccessful
SMB_NO_SUCH_FILE=0xc000000fL
SMB_ACCESS_DENIED=0xc0000022L
SMB_OBJECT_TYPE_MISMATCH=0xC0000024L
SMB_NOT_SAME_DEVICE=0xC00000d4L
STATUS_WRONG_VOLUMN=0xC0000012L
STATUS_OBJECT_NAME_NOT_FOUND=0xC0000034L

NEEDSPADDING=[SMB_SESSION_SETUP_ANDX]
ALL_ANDX=[SMB_TREE_CONNECT_ANDX,SMB_SESSION_SETUP_ANDX,SMB_READ_ANDX,SMB_CREATE_ANDX]

GET_DFS_REFERRAL=0x0010
QUERY_FILE_INFO=0x0007
FIND_FIRST2=0x0001
QUERY_PATH_INFO=0x0005
QUERY_FS_INFO=0x0003
SET_FILE_INFO=0x0008

QUERY_FILE_BASIC_INFO=1004
QUERY_FILE_STANDARD_INFO=1005

class SMBServer:
    """
    A useful little SMB Server
    """
    def __init__(self,host,port,getsock=None):
        self.getsock=getsock
        self.host=host
        self.port=port
        self.files={}
        self.clientsock=None
        self.target=""
        self.timeout=120
        
        #these functions take 2 arguments, header (tuple) and body (string data)
        response_functions={}
        response_functions[SMB_NEGOTIATE_PROTOCOL]=self.negotiateprotocol
        response_functions[SMB_SESSION_SETUP_ANDX]=self.andx_handler
        response_functions[SMB_TREE_CONNECT_ANDX]=self.andx_handler
        response_functions[SMB_TREE_CONNECT]=self.treeconnect
        response_functions[SMB_CHECK_DIRECTORY]=self.checkdirectory
        response_functions[SMB_ECHO_REQUEST]=self.echo
        response_functions[SMB_CREATE_ANDX]=self.andx_handler
        response_functions[SMB_CLOSE]=self.smbclose
        response_functions[SMB_TREE_DISCONNECT]=self.treedisconnect
        response_functions[SMB_TRANS2]=self.trans2
        response_functions[SMB_READ_ANDX]=self.andx_handler
        
        andxfunctions={}
        andxfunctions[SMB_READ_ANDX]=self.read_andx
        andxfunctions[SMB_CREATE_ANDX]=self.create_andx
        andxfunctions[SMB_SESSION_SETUP_ANDX]=self.sessionsetup_andx
        andxfunctions[SMB_TREE_CONNECT_ANDX]=self.treeconnect_andx

        trans2_response_functions={}
        trans2_response_functions[GET_DFS_REFERRAL]=self.get_dfs_referral
        trans2_response_functions[QUERY_FILE_INFO]=self.query_file_info
        trans2_response_functions[FIND_FIRST2]=self.find_first2
        trans2_response_functions[QUERY_PATH_INFO]=self.query_path_info
        trans2_response_functions[QUERY_FS_INFO]=self.query_fs_info
        trans2_response_functions[SET_FILE_INFO]=self.set_file_info

        self.andxfunctions=andxfunctions
        self.trans2_response_functions=trans2_response_functions
        self.response_functions=response_functions
        self.tid=1
        self.currentdata=""
        return

    def listen(self, queue=5):
        """listen on the socket"""
        if self.getsock:
            self.s=self.getsock.gettcplistener(self.port, self.host)
            if not self.s:
                return 0
        else:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try:
                s.bind((self.host, self.port))
                s.listen(queue)
            except:
                return 0
            self.s=s

        return 1
    
    def set_file_data(self,name,data):
        """any file you retrieve from the server with a particular name is this file"""
        self.files[name]=data
        return

    def accept(self):
        """Accept a connection from an SMB Client"""
        self.s.set_timeout(self.timeout)
        try: 
            (s2,addr)=self.s.accept()
        except:
            #failed
            print "SMBServer accept failed"
            return 0
        if self.target != "":
            if addr[0] != self.target:
                print "Client address (%s) does not match target address, ignoring"%(addr[0])
                return 0
        print "SMBServer accept succeeded from host %s:%s"%(addr)
        self.clientsock=s2
        return 1
        
    def handle(self):
        if self.clientsock==None:
            print "Trying to handle, but no client socket"
            return 0
        print "Attempting to handle a request from the client"
        try:
            data=recvnetbios_server(self.clientsock)
        except IndexError:
            print "Connection closed."
            return 0
        except:
            import traceback
            traceback.print_exc(file=sys.stdout)
            self.clientsock.close()
            return 0
        self.respond_to_netbios_request(data)
        return 1
        
    def respond_to_netbios_request(self,data):
        """Respond to a packet"""
        print "Responding to netbios request"
        if ord(data[0])==NETBIOS_SESSION_REQUEST:
            #we have to respond to a session request if we are on port 139
            print "Session request ... responding with success"
            netbiosresponse="\x82"+"\x00"*3 #simple
            self.clientsock.sendall(netbiosresponse)
        else:
            #just handle the smb request now...
            self.respond_to_smb_request(data[4:])
            
    def respond_to_smb_request(self,data):
        print "responding to smb request"
        format="<4sBLBH12sHHHHB"
        size=struct.calcsize(format)
        print "SMB header size=%d"%size
        header=struct.unpack(format,data[:size])
        (_,cmd,status,flags,flags2,sig,tid,pid,uid,mid,wordcount)=header
        self.pid=pid
        self.uid=uid
        self.mid=mid
        params=data[size:size+wordcount*2]
        data2=data[size+wordcount*2:]
        if cmd not in self.response_functions.keys():
            print "%x not in response functions!"%cmd
            return 0
        self.response_functions[cmd](header,params,data2)
        print ""
        return 1
        
    def sendsmb(self,cmd, status, flags, flags2, tid, mid, params = '', data = ''):
        uid=0

        wordcount=len(params)/2
        if len(params) & 1:
            print "Odd length of params is not supported..."
        print "Length of data=%s"%len(data)
        #print "data=%s"%hexprint(data)
        print "Length of params=%s"%len(params)
        fs='<4sBLBH12sHHHHB'
        padlen=0
        if len(data)>0 and cmd in [SMB_TRANS2]:
            padlen=(struct.calcsize(fs)+len(params)+len(data))%2

        padding="\x00"*padlen
        print "parenlen=%d Padlen=%d"%(len(params),padlen)
        #padding="\x00"
        #if len(data)==0:
        #    padding=""
        #    #no need
            
        print "cmd=%x"%cmd
        print "status=%x"%status
        print "flags=%x flags2=%x"%(flags,flags2)
        print "tid=%x"%tid
        
        pkt=struct.pack(fs, '\xffSMB', cmd, status, flags, flags2, '\0' * 12, 
                        tid, self.pid, self.uid, mid, wordcount)
        if cmd not in ALL_ANDX:
            pkt+=params + struct.pack('<H', len(data)) + padding + data
        else:
            pkt+=params+data #ANDX does its own thing
            
        pkt=netbios(pkt)
        self.clientsock.sendall(pkt)
        return 
    
    def parsesmb(self,data):
        """not used"""
        format='<4sBLBH12sHHHHB'
        _,cmd,status,flags,flags2,session,tid,pid,uid,mid,wordcount=struct.unpack(format,data)
        wordcount=wordcount*2
        params=data[size:size+wordcount]
        data2=data[size+wordcount:]
        bytecount=struct.unpack("<H",data2)
        ret={}
        ret["cmd"]=cmd
        ret["status"]=status
        ret["flags"]=flags
        ret["flags2"]=flags2
        ret["session"]=session #ingored
        ret["tid"]=tid
        ret["pid"]=pid
        ret["uid"]=uid
        ret["mid"]=mid
        ret["params"]=params
        ret["data"]=data
        return 
                 
    #### protocol handlers
    
    def negotiateprotocol(self,header,params,body):
        wordcount=header[10]
        data=body
        prots=data.split("\x02")
        print prots
        index=prots.index("NT LM 0.12\x00")
        print "Neg prot"
        flags=0x88
        flags2=0xc001
        mid=1
        paramformat="<HBHHLLLL8sHB"
        dialectindex=index-1
        securitymode=0x3
        maxmpxcount=50
        maxVCs=1
        maxbuffersize=16644
        maxrawbuffer=65536
        sessionkey=0
        capabilities=0x0000e3fd
        systemtime="\x00"*8
        servertimezone=0x01e0
        key="\x00"*8 #we need to fuzz this
        keylength=len(key)
        params=struct.pack(paramformat, dialectindex,securitymode,maxmpxcount,maxVCs,maxbuffersize,
                           maxrawbuffer,sessionkey,capabilities,systemtime,servertimezone,keylength)
        data=key+msunistring("VMWARE")+msunistring("WIN2KSRV")
        self.sendsmb(SMB_NEGOTIATE_PROTOCOL,SMB_SUCCESS,flags,flags2,self.tid,self.mid,params,data)
        return 1
        
    def andx_handler(self,header,params,body):
        """this had to be handled specially!"""
        andxcmd=int(header[1])
        firstandx=andxcmd
        response=""
        topparams=params
        firstparams=None
        topbody=body
        print "len(body)=%d"%len(body)
        offset=struct.unpack("<H",params[2:4])[0]
        print "offset=%d"%offset
        offset=offset-len(topparams)-33+1
        print "offset-33+1=%d"%offset
        print "len(body)=%d"%len(body)
        
        while andxcmd!=0xff: #end of ANDX
            
            nextbody=topbody[offset:]
            oldandxcmd=andxcmd
            print "Handling andx function %x"%andxcmd
            if len(body)>0:
                    bodylen=struct.unpack("<H",body[:2])[0]
                    if andxcmd in NEEDSPADDING:
                        addme=1
                    else:
                        addme=0
                    body=body[2+addme:2+bodylen]
            success,andxcmd,andxparams,andxdata=self.andxfunctions[andxcmd](params,body)
            #add wordcount and bytecount here with struct.pack. No padding is added. 
            #+2 here for the andxcommand+reserved+andxoffset
            if oldandxcmd in NEEDSPADDING:
                andxdata="\x00"+andxdata
            reserved=0
            andxoffset=len(andxparams)+len(andxdata)+4+32+3 #+offset-33+1
            if andxcmd==0xff:
                andxoffset=0
            andxparams=struct.pack("<BBBH",len(andxparams)/2+2,andxcmd,reserved,andxoffset)+andxparams
            if firstparams==None:
                firstparams=andxparams[1:] #strip off the wordcount, since that's added by sendsmb
            else:
                response+=andxparams
            response+=struct.pack("<H",len(andxdata))+andxdata #nice and slow, sorry
            if andxcmd!=0xff:
                body=nextbody
                print "body=*%s*"%hexprint(body)
                wordcount=struct.unpack("<B",body[0:1])[0]
                params=body[:wordcount*2]
                body=body[wordcount*2:]
                
                    
                    
                offset=andxoffset
            
        flags=0x88
        flags2=0xc001
        params=firstparams
        data=response

        self.sendsmb(firstandx,success,flags,flags2,self.tid,self.mid,params,data)

        
    
    def sessionsetup_andx(self,params,body):
        print "Sessionsetup ANDX"
        #andx stuff
        andxcommand=struct.unpack("<B",params[0:1])[0]
        data=msunistring("OS")+msunistring("LANMAN")
        
        action=1 #logged in as guest
        params=struct.pack('<H',action)        
        return SMB_SUCCESS,andxcommand,params,data
    
    def smbclose(self,header,params,body):
        print "smb close"
        flags=0x88
        flags2=0xc001
        params=""
        data=""
        self.sendsmb(SMB_CLOSE,SMB_SUCCESS,flags,flags2,self.tid,self.mid,params,data)
        return 1
    
    def treedisconnect(self,header,params,body):
        cmd=header[1]
        flags=0x88
        flags2=0xc001
        params=""
        data=""
        print "tree disconnect"
        self.sendsmb(cmd,SMB_SUCCESS,flags,flags2,self.tid,self.mid,params,data)
        return 1
    
    def treeconnect_andx(self,params,body):
        notes="""
        http://ubiqx.org/cifs/figures/smb-05.html
        The AndXOffset value in each AndX parameter block gives
        the offset (relative to the start of the SMB) of the next AndX block.
        The AndXOffset of the last AndX block has a value of zero (0).
        
        whatever.
        """
        print "Treeconnect"
        andxcommand=struct.unpack("<B",params[0:1])[0]
        print "Next andx = %x"%andxcommand
        optionalsupport=0x0001
        paramformat="<H"
        data="A:\x00"+msunistring("NTFS")
        #data="A:"*1024+"\x00"+msunistring("NTFS")
        params=struct.pack(paramformat,optionalsupport)
        return SMB_SUCCESS,andxcommand,params,data
    
    def create_andx(self,params,body):
        print "Handing create_andx"
        print "Create ANDX params(%d)=%s"%(len(params),hexprint(params))
        print "Create ANDX body(%d)=%s"%(len(body),hexprint(body))

        createaction=1
        infs="<BBHBHLLLLLLLLLLB"
        paramlength=struct.calcsize(infs)
        print "Paramlength=%d"%paramlength
        tup=struct.unpack(infs,params[:paramlength])
        andxcommand=tup[0]
        createflags=tup[5]
        canbedir=createflags & 0x08
        createoptions=tup[-4]
        mustbedir=createoptions & 0x1
        batchlock=createoptions & 0x2
        
        print "createflags=%8.8x"%createflags
        namelength=tup[-1] #bytecount
        #for padding byte
        #bodylength+=1
        name=read_unicode_string(body)[0].replace("\x00","")
        if name=="":
            name="\\"
        print "Trying to create_andx name *%s*"%(prettyprint(name))

        data=""        
        ourfilename=name.split("\\")[-1]
        success=SMB_SUCCESS
        if name=="":
            isdirectory=1
        elif name[-1]=="\\":
            isdirectory=1
        elif ourfilename in self.files:
            isdirectory=0
        else:
            createaction=0
            isdirectory=0
            success=STATUS_OBJECT_NAME_NOT_FOUND
            
        params=""

        cmd=SMB_CREATE_ANDX
        
        andxcommand=0xff
        reserved=0x00
        paramformat="<BHL8s8s8s8sLLLLLHHB"
        andxoffset=0
        if batchlock:
            oplock=2 #batch oplock granted
        else:
            oplock=0
        self.fid=random.randint(32,540) & 0xfffffff0L

        print "Set self.fid to %2x"%self.fid
        #data="A"*12
        zero=0
        faketime=binstring("e05eae8a1b6fc401")
        if isdirectory:
            allocationsize=0
        else:
            self.currentdata=self.files.get(ourfilename,self.currentdata)
            allocationsize=len(self.currentdata)
        endoffile=allocationsize
        fileattributes=0
        smb_device=0x40
        smb_directory=0x10
        smb_normal=0x80
        smb_readonly=0x01
        
        if name=="\\":
            fileattributes|=smb_directory 
            retval=SMB_CHECK_DIRECTORY
            
        elif isdirectory:
            fileattributes|=smb_directory #Directory 
        else:
            fileattributes|=smb_normal  #normal

        filetype=0            

        ipcount=0
        ipcstate=0+ipcount #eh?
        
        params=struct.pack(paramformat,oplock,self.fid,createaction,
                           faketime,faketime,faketime,faketime,fileattributes,
                           allocationsize,0,endoffile,0,filetype,ipcstate,isdirectory)
        

        print "isdirectory=%d and canbedir=%d"%(isdirectory,canbedir)
        if not isdirectory and  mustbedir:
            retval=SMB_NO_SUCH_FILE
        return success,andxcommand,params,data


    
    def read_andx(self,params,body):
        print "Handing read_andx"
        print "READ ANDX params(%d)=%s"%(len(params),hexprint(params))
        print "READ ANDX body(%d)=%s"%(len(body),hexprint(body))

        readfs="<BBHHLHHLHL"
        tup=struct.unpack(readfs,params[:struct.calcsize(readfs)])
        (andxcommand,_,andxoffset,fid,offset,max_count,
         min_count,max_count_high,remaining,high_offset)=tup

        params=""
        print "ReadANDX from %d to %d"%(offset,offset+max_count)
        data=self.currentdata[offset:offset+max_count]
        reserved=0x00
        paramformat="<HHHHHL6s"
        andxoffset=0

        datalength=len(data)
        datalengthhigh=0
        dataoffset=struct.calcsize(paramformat)+33+6 #why 6?
        remaining=len(self.currentdata[offset+max_count:])
        if remaining==0:
            remaining=-1 #-1 means end of file, retardedly
        #remaining=remaining
        datacompactionmode=0
        
        params=struct.pack(paramformat,
                           remaining,datacompactionmode, reserved,
                           datalength,dataoffset,datalengthhigh,
                           "\x00"*6)
        #params+="A"*20
        #self.sendsmb(cmd,SMB_SUCCESS,flags,flags2,self.tid,self.mid,params,data)
        return SMB_SUCCESS,andxcommand,params,data
        
    def treeconnect(self,header,params,body):
        print "Treeconnect"
        cmd=header[1]
        flags=0x88
        flags2=0xc001
        paramformat="<HH"
        maxbuf=1024
        treeid=self.tid
        #data=msunistring("A:NTFS")
        data=""
        params=struct.pack(paramformat,maxbuf,treeid)
        self.sendsmb(cmd,SMB_SUCCESS,flags,flags2,self.tid,self.mid,params,data)
        return 1
    
    def checkdirectory(self,header,body):
        print "Sessionsetup"
        flags=0x88
        flags2=0xc001
        params=""
        data=""

        self.sendsmb(SMB_CHECK_DIRECTORY,SMB_SUCCESS,flags,flags2,self.tid,self.mid,params,data)
        return 1
        
    def echo(self,header,params,body):
        print "Echo called"
        cmd=header[1]
        wordcount=header[10]
        data=body
        echocount=struct.unpack("<H",params)[0]
        echodata=data*echocount
        self.sendsmb(cmd,SMB_SUCCESS,flags,flags2,self.tid,self.mid,"",echodata)
        return 1
  
    def trans2(self,header,params,body):
        print "trans2"
        flags=0x88
        flags2=0xc001
        outparams=""
        outdata=""        
        
        cmd=header[1]
        wordcount=header[10]        

        paramstring="<HHHHBBHLHHHHHBBH"
        paramsize=struct.calcsize(paramstring)
        print "Paramsize=%d len params=%d"%(paramsize,len(params))
        print "Params=%s"%hexprint(params)
        tup=struct.unpack(paramstring,params[:paramsize])
        (totalparamcount,totaldatacount,maxparamcount,maxdatacount,
         maxsetupcount,_,trans2flags,timeout,_,paramcount,paramoffset,
         datacount,dataoffset,setupcount,_,subcommand)=tup
        
        realparamoffset=paramoffset-33-wordcount*2
        realparams=body[realparamoffset:realparamoffset+paramcount]
        print "realparams=%s"%hexprint(realparams)
        realdataoffset=paramoffset+dataoffset #???
        #need to strip off the body count and the padding here...
        realdataoffset+=3 #TODO: see if this is always true.
        
        realdata=body[realdataoffset:realdataoffset+datacount]
        print "realdata=%s"%hexprint(realdata)
        
        success,outparams,outdata=self.trans2_response_functions[subcommand](tup,realparams,realdata)
        outsetup=""

        totalparamcount=len(outparams)
        totaldatacount=len(outdata)
        reserved=0
        timeout=0
        paramcount=len(outparams)
        setupcount=len(outsetup)
        paramoffset=56+setupcount
        paramdisplacement=0
        datadisplacement=0
        dataoffset=paramoffset+paramcount
        datacount=len(outdata)
        
        paramfs="<HHHHHHHHHBB"
        padnum=0
        padding="\x00"*padnum
        tup=(totalparamcount,totaldatacount,reserved,paramcount,paramoffset,
             paramdisplacement,datacount,dataoffset,datadisplacement,
             setupcount,reserved)
        params=struct.pack(paramfs,*tup)

        self.sendsmb(cmd,success,flags,flags2,self.tid,self.mid,params,padding+outparams+outsetup+outdata)
        return 1
    
    def get_dfs_referral(self,header,params,data):
        print "Get dfs referral"
        params=""
        data="A"*20
        return params,data
    
    def query_file_info(self,header,params,data):
        print "Query File Info"

        attribs=intel_order(0x80)
        faketime=binstring("e05eae8a1b6fc401")

        fs="<HH"
        fid,interest=struct.unpack(fs,params[:struct.calcsize(fs)])
        print "FID=%x interest=%d"%(fid,interest)
        if interest==QUERY_FILE_BASIC_INFO:
            data=faketime*4+attribs
        elif interest==QUERY_FILE_STANDARD_INFO:
            sizeoffile=len(self.currentdata)
            #allocation size and disk size
            data+=(intel_order(sizeoffile)+intel_order(0))*2
            data+=intel_order(1) #link
            data+="\x00" #delete pending
            isdirectory=0 #make this work later...
            data+=chr(isdirectory)
        params="\x00"*2 #EA Error Offset =0
        return SMB_SUCCESS,params,data

    def pack_file_entry(self):

        nextentryoffset=0 #L
        fileindex=0 #L
        faketime=binstring("e05eae8a1b6fc401")
        filename="\\hi.exe"
        name=msunistring(filename)
        ourfilename=filename.split("\\")[-1]
        data=self.files.get(ourfilename,self.currentdata)
        #do this file
        self.currentdata=data
        
        create=faketime
        access=faketime
        write=faketime
        change=faketime
        endoffile=len(data) #LL
        allocationsize=len(data) #LL
        attributes=0x80 #L
        filenamelength=len(name) #L
        ealistlength=0 #L
        shortfilename=msunistring(filename)+"\x00"*20
        shortfilename=shortfilename[:24] #always 24 bytes
        shortfilenamelength=len(filename)*2 #B
        reserved=0 #B
        
        fs="<LL8s8s8s8sLLLLLLLBB24s"
        data=struct.pack(fs,nextentryoffset,fileindex,create,access,write,
                         change,endoffile,reserved,allocationsize,reserved,attributes,
                         filenamelength,ealistlength,
                         shortfilenamelength,reserved,shortfilename)
        data+=name
        return data
    
        
    def find_first2(self,header,params,data):
        print "Find First 2"
        paramfs="<HHHHH"
        searchid=0
        searchcount=1
        endofsearch=1
        eaerroroffset=0
        data=self.pack_file_entry()
        lastnameoffset=len(data)
        
        params=struct.pack(paramfs,searchid,searchcount,endofsearch,eaerroroffset,lastnameoffset)

        return SMB_SUCCESS,params,data
    
    def query_path_info(self,header,params,data):
        print "Query Path Info"
        print "params=%s"%hexprint(params)
        print "data=%s"%hexprint(data)
        levelofinterest=struct.unpack("<H",params[:2])
        
        fileparam,_=read_unicode_string(params[6:])
        print "fileparam to read is %s"%fileparam
        
        params="\x00"*2 #EA Error Offset =0
        success=SMB_SUCCESS
        if fileparam=="":
            attribs=intel_order(0x10) #directory
        elif fileparam in self.files:
            attribs=intel_order(0x80) #just normal, nothing else...
        else:
            success=STATUS_OBJECT_NAME_NOT_FOUND
            return success,"",""
        
        faketime=binstring("e05eae8a1b6fc401")
        
        data=faketime*4+attribs
        #testing, testing, 123
        data+="\x00"*4 #must be there - dunno why. Ethereal doesn't know it, but smb does.
        return success,params,data

    def query_fs_info(self,header,params,data):
        print "Query FS Info"
        params=""
        data=""
        return SMB_SUCCESS,params,data    
    
    def set_file_info(self,header,params,data):
        print "Set File Info"
        params=""
        data=""
        return SMB_SUCCESS,params,data    
    
if __name__=="__main__":
    data=file("/etc/passwd","rb").read()
        
    print "Starting smb server"
    mysmbserver=SMBServer("0.0.0.0",445)

    # testing checking mechanism
    mysmbserver.target = "192.168.1.104"
    mysmbserver.set_file_data("/etc/passwd",data) #load the file up
    
    if mysmbserver.listen()==0:
        print "Could not listen!"
        sys.exit(1)
    print "Accepting"
    while mysmbserver.accept() == 0:
        print "Waiting for new client..."
    if 1:
        while mysmbserver.handle():
            print "Handled."
        time.sleep(1)
    print "Sleeping"
    time.sleep(10)        