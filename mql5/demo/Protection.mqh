#ifndef FX_DEMO_PROTECTION
#define FX_DEMO_PROTECTION
#include "../integration/DisabledKernel.mqh"
// Independent retained checkpoint is mandatory on restart; no implicit reset.
class DemoProtectionStore
{
private:
   FxJournal journal;
   string ids[],scope;
   SProtection states[];
   bool loaded;
   int Find(string id){ for(int i=0;i<ArraySize(ids);i++) if(ids[i]==id) return i; return -1; }
   bool Save(string id,const SProtection &s)
   {
      string row=id+"\t"+s.phase+"\t"+s.boot+"\t"+IntegerToString(s.submitted)+"\t"+IntegerToString(s.repair)+"\t"+
         IntegerToString(s.exit)+"\t"+IntegerToString(s.last)+"\t"+(s.hard ? "1" : "0");
      if(!loaded || !journal.Append(row)) { loaded=false; return false; }
      int i=Find(id); if(i<0){ i=ArraySize(ids); ArrayResize(ids,i+1); ArrayResize(states,i+1); ids[i]=id; }
      states[i]=s; return true;
   }
public:
   DemoProtectionStore(){ loaded=false; }
   void Close(){ journal.Close(); loaded=false; }
   bool Open(string path,string binding,bool bootstrap,string retained_tip)
   {
      Close(); ArrayResize(ids,0); ArrayResize(states,0); scope=binding;
      if(!FxHex(binding,64) || (bootstrap ? (FileIsExist(path) || retained_tip!="") : (!FileIsExist(path) || !FxHex(retained_tip,64)))) return false;
      string rows[]; if(!journal.Open(path,rows)) return false;
      if(bootstrap) { loaded=journal.Append("PROTECTION_BIND\t"+scope); return loaded; }
      if(ArraySize(rows)<1 || rows[0]!="PROTECTION_BIND\t"+scope || DgRowsTip(rows)!=retained_tip) { Close(); return false; }
      for(int n=1;n<ArraySize(rows);n++)
      {
         string f[]; if(StringSplit(rows[n],'\t',f)!=8 || !FxUuid(f[0]) || !FxHex(f[2],64) || (f[7]!="0" && f[7]!="1")) { Close(); return false; }
         for(int j=3;j<7;j++) if(!FxInteger(f[j])) { Close(); return false; }
         if(f[1]!="PENDING" && f[1]!="PROTECTED" && f[1]!="CLOSED" && f[1]!="UNKNOWN" && f[1]!="REPAIRING" && f[1]!="REPAIR_REJECTED" && f[1]!="EXITING" && f[1]!="EXIT_REJECTED") { Close(); return false; }
         SProtection p; p.phase=f[1]; p.boot=f[2]; p.submitted=StringToInteger(f[3]); p.repair=StringToInteger(f[4]); p.exit=StringToInteger(f[5]); p.last=StringToInteger(f[6]); p.hard=f[7]=="1";
         if(p.repair<=p.submitted || p.exit<=p.repair || p.last<p.submitted) { Close(); return false; }
         int i=Find(f[0]);
         if(i<0){ i=ArraySize(ids); ArrayResize(ids,i+1); ArrayResize(states,i+1); ids[i]=f[0]; }
         else if((states[i].hard && !p.hard) || states[i].submitted!=p.submitted || states[i].repair!=p.repair || states[i].exit!=p.exit || p.last<states[i].last) { Close(); return false; }
         states[i]=p;
      }
      loaded=true; return true;
   }
   bool Begin(string id,long now,string boot,long repair_ms,long exit_ms)
   {
      if(!loaded || !FxUuid(id) || !FxHex(boot,64) || Find(id)>=0 || repair_ms<=0 || exit_ms<=repair_ms || exit_ms>60000) return false;
      SProtection p; p.phase="PENDING"; p.boot=boot; p.submitted=now; p.repair=now+repair_ms; p.exit=now+exit_ms; p.last=now; p.hard=false;
      return Save(id,p);
   }
   bool Has(string id){ return loaded && Find(id)>=0; }
   bool HardHalt(){ if(!loaded) return true; for(int i=0;i<ArraySize(states);i++) if(states[i].hard) return true; return false; }
   bool Unresolved(){ if(!loaded) return true; for(int i=0;i<ArraySize(states);i++) if(states[i].phase!="CLOSED" && states[i].phase!="PROTECTED") return true; return false; }
   string Step(string id,long now,string boot,bool broker,bool reconciled,bool protected_ok,bool closed,bool unknown,bool rejected,bool submission_enabled)
   {
      int i=Find(id); if(!loaded || i<0) return "STORAGE_OR_STATE_MISSING";
      SProtection actual=states[i],proposed; bool suppressed=false;
      string action=DgProtection(actual,proposed,now,boot,true,broker,reconciled,protected_ok,closed,unknown,rejected,suppressed);
      // Durable intent before an enabled mutation; disabled recommendations cannot
      // create fictitious REPAIRING/EXITING states.
      if(submission_enabled && suppressed) actual=proposed;
      if(!Save(id,actual)) return "JOURNAL_UNAVAILABLE";
      return action;
   }
};
#endif
