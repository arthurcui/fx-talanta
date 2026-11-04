#ifndef FX_DEMO_STATE_OUTBOX
#define FX_DEMO_STATE_OUTBOX
#include "../integration/DisabledKernel.mqh"
// Positive broker observations only. Durable outbox is independent of work ACKs.
class DemoStateOutbox
{
private:
   FxJournal journal;string reports[],scope;int acknowledged;bool loaded;
public:
   DemoStateOutbox(){loaded=false;acknowledged=0;}
   void Close(){journal.Close();loaded=false;}
   string Pending(){return loaded && acknowledged<ArraySize(reports) ? reports[acknowledged] : "";}
   bool Open(string path,string binding,bool bootstrap,string tip)
   {
      Close();scope=binding;ArrayResize(reports,0);acknowledged=0;
      if(!FxHex(scope,64) || (bootstrap ? (FileIsExist(path) || tip!="") : (!FileIsExist(path) || !FxHex(tip,64)))) return false;
      string rows[];if(!journal.Open(path,rows))return false;
      if(bootstrap){loaded=journal.Append("STATE_BIND\t"+scope);return loaded;}
      if(ArraySize(rows)<1 || rows[0]!="STATE_BIND\t"+scope || DgRowsTip(rows)!=tip){Close();return false;}
      loaded=true;
      for(int i=1;i<ArraySize(rows);i++)
      {
         string f[],payload,p[];
         if(StringSplit(rows[i],'\t',f)!=2){Close();return false;}
         if(f[0]=="STATE" && ShUnhex(f[1],payload) && StringSplit(payload,'\t',p)==14 && p[0]=="demo-state/1")
         {int n=ArraySize(reports);ArrayResize(reports,n+1);reports[n]=payload;}
         else if(f[0]=="ACK" && Pending()!="" && FxHash(Pending())==f[1]) acknowledged++;
         else {Close();return false;}
      }
      return true;
   }
   bool Ack(string hash)
   {
      if(Pending()=="" || FxHash(Pending())!=hash)return false;
      if(!journal.Append("ACK\t"+hash)){loaded=false;return false;}acknowledged++;return true;
   }
   bool Publish(const FxEntry &e,long at,int error,string proof,bool positive)
   {
      if(!loaded || !positive || FxScope(e.work)!=scope || error<0 || error>100 || !FxHex(proof,64))return false;
      if(e.state!="PROTECTED" && e.state!="PROTECTION_PENDING" && e.state!="CLOSED")return false;
      for(int i=ArraySize(reports)-1;i>=0;i--)
      {string f[];StringSplit(reports[i],'\t',f);if(f[1]==e.work.id){if(StringToInteger(f[3])>=e.version)return StringToInteger(f[3])==e.version;break;}}
      if(ArraySize(reports)>=10000)return false;
      string body="demo-state/1\t"+e.work.id+"\t"+e.work.digest+"\t"+IntegerToString(e.version)+"\t"+e.state+"\t"+
         IntegerToString(e.filled)+"\t"+IntegerToString(e.open_volume)+"\t"+IntegerToString(e.remaining)+"\t"+
         IntegerToString((long)e.order)+"\t"+IntegerToString((long)e.position)+"\t"+FxDecimal(e.accepted_stop)+"\t"+
         IntegerToString(at)+"\t"+IntegerToString(error)+"\t"+proof;
      if(!journal.Append("STATE\t"+ShHex(body))){loaded=false;return false;}
      int n=ArraySize(reports);ArrayResize(reports,n+1);reports[n]=body;return true;
   }
};
#endif
