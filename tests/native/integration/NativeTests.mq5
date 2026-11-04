#property strict
#property tester_file "disabled-binding.tsv"
#property tester_file "disabled-cases.tsv"
#include "../../../mql5/integration/DisabledKernel.mqh"
int check_file=INVALID_HANDLE;
void Check(string name,bool ok){ FileWriteString(check_file,name+"\t"+(ok ? "1" : "0")+"\r\n"); }
int OnInit()
{
   if(!MQLInfoInteger(MQL_TESTER)) return INIT_FAILED;
   int binding=FileOpen("disabled-binding.tsv",FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(binding==INVALID_HANDLE) return INIT_FAILED;
   string b[]; int count=StringSplit(FileReadString(binding),'\t',b); FileClose(binding);
   if(count!=5) return INIT_FAILED;
   int cases=FileOpen("disabled-cases.tsv",FILE_READ|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   int output=FileOpen("disabled-results.tsv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   check_file=FileOpen("disabled-checks.tsv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(cases==INVALID_HANDLE || output==INVALID_HANDLE || check_file==INVALID_HANDLE) return INIT_FAILED;
   string first=""; long first_now=0; int index=0;
   while(!FileIsEnding(cases))
   {
      string f[],packet;
      if(StringSplit(FileReadString(cases),'\t',f)!=4 || !ShUnhex(f[3],packet)) return INIT_FAILED;
      if(first==""){ first=packet; first_now=StringToInteger(f[1]); }
      DgKernel kernel;
      bool opened=kernel.Open("case-"+IntegerToString(index++)+".journal",b[0],b[1],b[2],b[3],b[4],true,"");
      bool received=opened && kernel.Receive(packet,StringToInteger(f[1]),(int)StringToInteger(f[2]));
      FileWriteString(output,f[0]+"\t"+(received ? "1" : "0")+"\t"+ShHex(kernel.Pending())+"\r\n");
      kernel.Close();
   }
   FileClose(cases); FileClose(output);
   DgKernel k;
   Check("missing-journal-refused",!k.Open("missing.journal",b[0],b[1],b[2],b[3],b[4],false,"") );
   Check("explicit-bootstrap",k.Open("recovery.journal",b[0],b[1],b[2],b[3],b[4],true,"") );
   Check("receipt-durable",k.Receive(first,first_now,0));
   string receipt=k.Pending(); k.Close(); string tip=DgFileTip("recovery.journal");
   Check("bootstrap-cannot-overwrite",!k.Open("recovery.journal",b[0],b[1],b[2],b[3],b[4],true,"") );
   Check("checkpoint-required",!k.Open("recovery.journal",b[0],b[1],b[2],b[3],b[4],false,"") );
   Check("checkpoint-conflict",!k.Open("recovery.journal",b[0],b[1],b[2],b[3],b[4],false,b[1]) );
   Check("restart-keeps-pending",k.Open("recovery.journal",b[0],b[1],b[2],b[3],b[4],false,tip) && k.Pending()==receipt);
   Check("duplicate-work-refused",!k.Receive(first,first_now,0));
   Check("wrong-ack-refused",!k.Ack(b[1]));
   Check("ack-persisted",k.Ack(FxHash(receipt)) && k.Pending()=="");
   k.Close(); string acknowledged_tip=DgFileTip("recovery.journal");
   Check("old-prefix-checkpoint-refused",!k.Open("recovery.journal",b[0],b[1],b[2],b[3],b[4],false,tip));
   SProtection p,q; p.phase="PENDING"; p.boot="fixture"; p.submitted=100; p.repair=200; p.exit=300; p.last=100; p.hard=false;
   bool suppressed=false; string action=DgProtection(p,q,150,"fixture",true,true,true,false,false,false,false,suppressed);
   bool repair=action=="ATTACH_STOP_ONCE" && suppressed && p.phase=="PENDING" && q.phase=="REPAIRING";
   action=DgProtection(p,q,310,"fixture",true,true,true,false,false,false,false,suppressed);
   Check("management-unsent-state-preserved",repair && action=="CONTROLLED_EXIT_ONCE" && suppressed && p.phase=="PENDING" && p.hard);
   FileClose(check_file);
   return INIT_SUCCEEDED;
}
void OnTick(){ TesterStop(); }
