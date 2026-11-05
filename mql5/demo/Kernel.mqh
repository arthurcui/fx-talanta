#ifndef FX_DEMO_KERNEL
#define FX_DEMO_KERNEL
#include "Runtime.mqh"
#include "StateOutbox.mqh"
class DemoKernel
{
private:
   DgKernel reference;
   DemoRuntime runtime;
   FxJournal outcomes;
   DemoStateOutbox broker_states;
   string ids[],reasons[],states[];
   bool loaded;
public:
   DemoKernel(){ loaded=false; }
   void Close(){ reference.Close(); runtime.Close(); outcomes.Close();broker_states.Close(); loaded=false; }
   FxGateway *State(){ return runtime.State(); }
   bool Open(string base,string scope,string client,string release,string policy,string key,bool bootstrap,
             string reference_tip,string execution_tip,string outcome_tip,string state_tip="")
   {
      Close(); ArrayResize(ids,0); ArrayResize(reasons,0); ArrayResize(states,0);
      string path=base+".outcomes",binding="DEMO_OUTCOME_BIND\t"+scope+"\t"+client+"\t"+release+"\t"+policy;
      if(bootstrap ? (FileIsExist(path) || outcome_tip!="") : (!FileIsExist(path) || !FxHex(outcome_tip,64))) return false;
      if(!reference.Open(base+".risk",scope,client,release,policy,key,bootstrap,reference_tip) ||
         !runtime.Open(base+".execution",scope,bootstrap,execution_tip)) { Close(); return false; }
      string rows[]; if(!outcomes.Open(path,rows)) { Close(); return false; }
      if(bootstrap) loaded=outcomes.Append(binding);
      else
      {
         if(ArraySize(rows)<1 || rows[0]!=binding || DgRowsTip(rows)!=outcome_tip) { Close(); return false; }
         for(int i=1;i<ArraySize(rows);i++)
         {
            string f[]; if(StringSplit(rows[i],'\t',f)!=3 || !FxUuid(f[0])) { Close(); return false; }
            int n=ArraySize(ids); ArrayResize(ids,n+1); ArrayResize(reasons,n+1); ArrayResize(states,n+1);
            ids[n]=f[0]; reasons[n]=f[1]; states[n]=f[2];
         }
         loaded=true;
      }
      if(loaded && !broker_states.Open(base+".states",scope,bootstrap,state_tip)) {Close();return false;}
      return loaded;
   }
   bool PublishState(const FxEntry &entry,long at,int error,string proof,bool positive)
   {return loaded && broker_states.Publish(entry,at,error,proof,positive);}
   bool ClosureReportsAcknowledged()
   {
      if(!loaded)return false;
      FxGateway *gateway=runtime.State();
      for(int i=0;i<gateway.Count();i++)
      {
         FxEntry entry=gateway.At(i);
         if(entry.state=="REJECTED")continue;
         if(entry.state!="CLOSED" || !broker_states.Acknowledged(entry))return false;
      }
      return true;
   }
   string Pending()
   {
      string receipt=reference.Pending(); if(receipt=="") return broker_states.Pending();
      string f[]; StringSplit(receipt,'\t',f); string reason="INTERRUPTED",state="INTERRUPTED";
      for(int i=0;i<ArraySize(ids);i++) if(ids[i]==f[1]){ reason=reasons[i]; state=states[i]; }
      if(state=="INTERRUPTED")
      {FxGateway *g=runtime.State();for(int i=0;i<g.Count();i++){FxEntry e=g.At(i);if(e.work.id==f[1] && (e.filled>0 || e.state=="SUBMITTING" || e.state=="OUTCOME_UNKNOWN" || e.state=="ACKNOWLEDGED"))state="OUTCOME_UNKNOWN";}}
      if(state=="ACKNOWLEDGED" || state=="SUBMITTING" || state=="OUTCOME_UNKNOWN")
         return "demo-receipt/2\t"+ShHex(receipt)+"\t"+reason+"\t"+state+"\t"+(state=="ACKNOWLEDGED" ? "ATTEMPTED" : "UNKNOWN");
      return "demo-receipt/1\t"+ShHex(receipt)+"\t"+reason+"\t"+state+"\t0";
   }
   bool Ack(string hash)
   {
      if(!loaded || Pending()=="" || hash!=FxHash(Pending()))return false;
      return reference.Pending()!="" ? reference.Ack(FxHash(reference.Pending())) : broker_states.Ack(hash);
   }
   bool Receive(string packet,long now,int error,DemoPort &port)
   {
      if(!loaded || Pending()!="") return false; // The native release gate remains in the fixed port.
      string f[],frame,disabled,risk,d[];
      if(StringSplit(packet,'\t',f)!=3 || f[0]!="demo-execution/1" || !ShUnhex(f[1],frame) || !ShUnhex(f[2],disabled) ||
         StringSplit(disabled,'\t',d)!=11 || !ShUnhex(d[1],risk)) return false;
      FxWork w; SLoss ledger;
      if(FxDecode(frame,w,true)!="OK" || !DgLedger(d,ledger)) return false;
      string r[],v[]; if(!ShWork(risk,FxScope(w),w.release,w.policy,r,v) || r[1]!=w.id || r[2]!=w.digest) return false;
      // Commit receipt intent before native admission. A crash in between is
      // reported INTERRUPTED on restore and is never automatically dispatched.
      if(!reference.Receive(disabled,now,error)) return false;
      string reason=runtime.Dispatch(frame,risk,ledger,port),state="NOT_ADMITTED";
      FxGateway *g=runtime.State(); for(int i=0;i<g.Count();i++){ FxEntry e=g.At(i); if(e.work.id==w.id) state=e.state; }
      if(!outcomes.Append(w.id+"\t"+reason+"\t"+state)) { loaded=false; return false; }
      int n=ArraySize(ids); ArrayResize(ids,n+1); ArrayResize(reasons,n+1); ArrayResize(states,n+1);
      ids[n]=w.id; reasons[n]=reason; states[n]=state; return true;
   }
};
#endif
