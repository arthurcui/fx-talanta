#property strict
#property tester_file "shadow-cases.tsv"
#property tester_file "shadow-auth.txt"
#include "Inbox.mqh"
int checks=0,failures=0,output=INVALID_HANDLE;
void Check(string name,bool ok)
{
   checks++; if(!ok) failures++;
   FileWriteString(output,name+"\t"+(ok ? "PASS" : "FAIL")+"\r\n");
}
int OnInit()
{
   if(!MQLInfoInteger(MQL_TESTER)) return INIT_FAILED;
   output=FileOpen("shadow-checks.tsv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   int input_file=FileOpen("shadow-cases.tsv",FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   int results=FileOpen("shadow-results.tsv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(output==INVALID_HANDLE || input_file==INVALID_HANDLE || results==INVALID_HANDLE) return INIT_FAILED;
   string first="",scope="",release="",policy="";
   while(!FileIsEnding(input_file))
   {
      string line=FileReadString(input_file),f[],work,parts[];
      bool valid=StringSplit(line,'\t',f)==4 && ShUnhex(f[3],work);
      Check("case-frame-"+IntegerToString(checks),valid);
      if(!valid) break;
      StringSplit(work,'\t',parts);
      scope=parts[3]; release=parts[4]; policy=parts[5];
      string receipt=ShAssess(work,scope,release,policy,StringToInteger(f[1]),(int)StringToInteger(f[2]));
      FileWriteString(results,f[0]+"\t"+ShHex(receipt)+"\r\n");
      if(first=="") first=work;
   }
   FileClose(input_file); FileClose(results);
   int auth=FileOpen("shadow-auth.txt",FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   string raw=FileReadString(auth),f[],op,payload; FileClose(auth);
   StringSplit(raw,'\t',f); string key="ssssssssssssssssssssssssssssssss";
   long now=StringToInteger(f[5]);
   Check("python-auth",ShDecode(raw,key,"C2S",scope,f[3],f[4],now,op,payload) && op=="PULL" && payload=="");
   Check("native-auth",ShEncode(key,"C2S",scope,f[3],f[4],now,"PULL","")==raw);
   Check("wrong-key",!ShDecode(raw,"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx","C2S",scope,f[3],f[4],now,op,payload));
   Check("wrong-direction",!ShDecode(raw,key,"S2C",scope,f[3],f[4],now,op,payload));
   Check("expired",!ShDecode(raw,key,"C2S",scope,f[3],f[4],now+5000,op,payload));
   Check("response-nonce",!ShDecode(raw,key,"C2S",scope,f[3],scope,now,op,payload));
   Check("tampered",!ShDecode(raw+"x",key,"C2S",scope,f[3],f[4],now,op,payload));
   string path="shadow-"+IntegerToString((long)GetTickCount64())+".journal";
   ShInbox inbox,second;
   Check("missing-inbox",!inbox.Open(path,scope,f[3],release,policy,key,false));
   Check("bootstrap",inbox.Open(path,scope,f[3],release,policy,key,true));
   Check("second-writer",!second.Open(path,scope,f[3],release,policy,key,false));
   Check("durable-receipt",inbox.Receive(first,now,0));
   string original=inbox.Pending();
   Check("duplicate-not-reevaluated",!inbox.Receive(first,now+1501,0) && inbox.Pending()==original);
   inbox.Close();
   Check("restart-retains-outbox",inbox.Open(path,scope,f[3],release,policy,key,false) && inbox.Pending()==original);
   Check("wrong-ack",!inbox.Ack(scope));
   Check("ack",inbox.Ack(FxHash(original)) && inbox.Pending()=="");
   inbox.Close();
   Check("restart-retains-ack",inbox.Open(path,scope,f[3],release,policy,key,false) && inbox.Pending()=="");
   Check("backend-rollback-blocked",!inbox.Receive(first,now,0));
   string conflict=first,old_fields[]; StringSplit(conflict,'\t',old_fields);
   old_fields[6]="2"; conflict="";
   for(int i=0;i<ArraySize(old_fields);i++) conflict+=(i==0 ? "" : "\t")+old_fields[i];
   Check("same-id-new-sequence-rejected",!inbox.Receive(conflict,now,0));
   inbox.Close();
   Check("wrong-binding",!inbox.Open(path,scope,f[3],policy,release,key,false));
   Check("no-bootstrap-reset",!inbox.Open(path,scope,f[3],release,policy,key,true));
   FileFlush(output); FileClose(output);
   Print("FX_SHADOW_TESTS checks=",checks," failures=",failures);
   return failures==0 ? INIT_SUCCEEDED : INIT_FAILED;
}
void OnTick(){}
double OnTester(){ return failures==0 ? checks : -failures; }
