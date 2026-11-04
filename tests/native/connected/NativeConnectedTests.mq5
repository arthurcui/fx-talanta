#property strict
#include "../../../mql5/connected/Inbox.mqh"
int checks=0,failures=0,output=INVALID_HANDLE;
void Check(string name,bool ok)
{
   checks++; if(!ok) failures++;
   FileWriteString(output,name+"\t"+(ok ? "PASS" : "FAIL")+"\r\n");
}
string Observation(string scope,string binding,string hash,long stamp,int sequence=1)
{
   return "connected-observation/1\t00000000-0000-4000-8000-000000000001\t"+IntegerToString(sequence)+"\t"+
      scope+"\t"+hash+"\t"+IntegerToString(stamp)+"\t"+IntegerToString(stamp+60000)+"\t10\tEURUSD\tEURUSD\t"+
      IntegerToString(stamp)+"\tCOSTS_UNQUALIFIED,NEWS_UNQUALIFIED\t"+binding+"\t7200000";
}
string NativeRead(string path)
{
   int file=FileOpen(path,FILE_READ|FILE_BIN);
   if(file==INVALID_HANDLE) return "";
   int count=(int)FileSize(file); uchar bytes[]; ArrayResize(bytes,count);
   FileReadArray(file,bytes); FileClose(file); return CharArrayToString(bytes,0,count,CP_UTF8);
}
bool NativeWrite(string path,string text)
{
   int file=FileOpen(path,FILE_WRITE|FILE_BIN);
   if(file==INVALID_HANDLE) return false;
   uchar bytes[]; int count=StringToCharArray(text,bytes,0,WHOLE_ARRAY,CP_UTF8)-1; ArrayResize(bytes,count);
   bool ok=(int)FileWriteArray(file,bytes)==count; FileFlush(file); FileClose(file); return ok;
}
int OnInit()
{
   if(!MQLInfoInteger(MQL_TESTER)) return INIT_FAILED;
   output=FileOpen("connected-inbox-checks.tsv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(output==INVALID_HANDLE) return INIT_FAILED;
   string scope,binding,client,incarnation,hash,key="ssssssssssssssssssssssssssssssss";
   StringInit(scope,64,'a'); StringInit(binding,64,'b'); StringInit(client,64,'c');
   StringInit(incarnation,64,'d'); StringInit(hash,64,'e');
   long stamp=1800000000000;
   string obs=Observation(scope,binding,hash,stamp),f[];
   Check("valid-observation",CoObservation(obs,scope,binding,f));
   Check("wrong-scope",!CoObservation(obs,client,binding,f));
   Check("wrong-binding",!CoObservation(obs,scope,client,f));
   string malformed=obs; StringReplace(malformed,"7200000","50400001");
   Check("offset-bound",!CoObservation(malformed,scope,binding,f));
   string receipt=CoReceipt(obs,scope,binding,stamp+100,10,stamp+20),r[];
   Check("valid-receipt",CoReceiptValid(obs,receipt,scope,binding));
   StringSplit(receipt,'\t',r);
   Check("measured-age",r[6]=="110" && r[8]=="90");
   Check("never-accepted",r[9]=="REQUIRED_INPUTS" && r[11]=="0");
   Check("original-missing-codes",r[10]=="COSTS_UNQUALIFIED,NEWS_UNQUALIFIED");
   string unavailable=CoReceipt(obs,scope,binding,stamp+100,10,0);
   StringSplit(unavailable,'\t',r);
   Check("unavailable-native",r[7]=="0" && r[8]=="-1" && r[9]=="NATIVE_DATA_UNAVAILABLE");
   string expired=CoReceipt(obs,scope,binding,stamp+59990,10,0);
   StringSplit(expired,'\t',r);
   Check("expiry-precedence",r[9]=="EXPIRED");
   string boundary=CoReceipt(obs,scope,binding,stamp+1990,10,stamp+20);
   StringSplit(boundary,'\t',r);
   Check("two-second-exact",r[6]=="2000" && r[9]=="REQUIRED_INPUTS");
   boundary=CoReceipt(obs,scope,binding,stamp+1991,10,stamp+20); StringSplit(boundary,'\t',r);
   Check("two-second-one-ms-over",r[6]=="2001" && r[9]=="QUOTE_STALE");
   boundary=CoReceipt(obs,scope,binding,stamp+100,10,stamp+101); StringSplit(boundary,'\t',r);
   Check("native-future",r[9]=="QUOTE_STALE");
   Check("clock-over-limit",CoReceipt(obs,scope,binding,stamp+100,101,stamp+20)=="");
   Check("future-measurement-deferred",CoReceipt(obs,scope,binding,stamp-1,10,stamp+20)=="");
   Check("receipt-tamper",!CoReceiptValid(obs,receipt+"0",scope,binding));
   string path="connected-test-"+IntegerToString((long)GetTickCount64())+"-"+IntegerToString((long)GetMicrosecondCount())+".journal";
   string checkpoint=path+".checkpoint";
   CoInbox inbox,second;
   Check("missing-no-bootstrap",!inbox.Open(path,checkpoint,scope,client,incarnation,"1",binding,key,false));
   Check("explicit-bootstrap",inbox.Open(path,checkpoint,scope,client,incarnation,"1",binding,key,true));
   Check("exclusive-writer",!second.Open(path,checkpoint,scope,client,incarnation,"1",binding,key,false));
   Check("durable-receipt",inbox.Receive(obs,receipt) && inbox.Pending()==receipt);
   Check("duplicate-pending-refused",!inbox.Receive(obs,receipt));
   Check("wrong-ack-refused",!inbox.Ack(hash) && inbox.Pending()==receipt);
   inbox.Close();
   string checkpoint_text=NativeRead(checkpoint),journal_text=NativeRead(path),cp[];
   StringSplit(checkpoint_text,'\t',cp);
   Check("exact-file-sha",ArraySize(cp)==8 && cp[4]==FxHash(journal_text));
   Check("receipt-checkpoint",cp[5]=="1" && cp[6]==FxHash(receipt) && cp[7]=="0\r\n");
   Check("restart-retains-receipt",inbox.Open(path,checkpoint,scope,client,incarnation,"1",binding,key,false) && inbox.Pending()==receipt);
   Check("ack-after-restart",inbox.Ack(FxHash(receipt)) && inbox.Pending()=="");
   inbox.Close();
   Check("restart-retains-ack",inbox.Open(path,checkpoint,scope,client,incarnation,"1",binding,key,false) && inbox.Pending()=="");
   Check("backend-rollback-refused",!inbox.Receive(obs,receipt));
   string second_obs=Observation(scope,binding,hash,stamp,2),second_receipt=CoReceipt(second_obs,scope,binding,stamp+100,10,stamp+20);
   Check("same-id-new-sequence-refused",!inbox.Receive(second_obs,second_receipt));
   inbox.Close();
   Check("wrong-epoch",!inbox.Open(path,checkpoint,scope,client,incarnation,"2",binding,key,false));
   Check("wrong-incarnation",!inbox.Open(path,checkpoint,scope,client,client,"1",binding,key,false));
   Check("bootstrap-cannot-reset",!inbox.Open(path,checkpoint,scope,client,incarnation,"1",binding,key,true));
   string latest=NativeRead(checkpoint);
   Check("fixture-checkpoint-rewind",NativeWrite(checkpoint,checkpoint_text));
   Check("joint-checkpoint-mismatch",!inbox.Open(path,checkpoint,scope,client,incarnation,"1",binding,key,false));
   Check("fixture-checkpoint-restore",NativeWrite(checkpoint,latest));
   Check("consistent-checkpoint-reopens",inbox.Open(path,checkpoint,scope,client,incarnation,"1",binding,key,false));
   inbox.Close();
   FileFlush(output); FileClose(output);
   Print("FX_CONNECTED_INBOX_TESTS checks=",checks," failures=",failures);
   return failures==0 ? INIT_SUCCEEDED : INIT_FAILED;
}
void OnTick(){}
double OnTester(){ return failures==0 ? checks : -failures; }
