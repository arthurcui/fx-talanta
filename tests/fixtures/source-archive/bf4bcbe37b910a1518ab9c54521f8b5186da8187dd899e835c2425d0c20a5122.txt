#ifndef FX_DEMO_ACCEPTANCE_BUDGET
#define FX_DEMO_ACCEPTANCE_BUDGET
#include "../integration/DisabledKernel.mqh"
// Independent native cap. This journal is not an execution activation token.
class DemoAcceptanceBudget
{
private:
   FxJournal journal;
   string scope,release,policy,currency,binding,rows[],ids[],hashes[];
   long begins,expires,last,reference,water,entry_bps,total_bps,lots[],cents[];
   bool closed[],healthy,expired;
   int Find(string id){for(int i=0;i<ArraySize(ids);i++)if(ids[i]==id)return i;return -1;}
   bool Apply(string row)
   {
      string f[];int n=StringSplit(row,'\t',f);
      if(n==1 && f[0]=="DRAIN")
      {if(expired)return false;expired=true;return true;}
      if(n==2 && f[0]=="EXPIRED")
      {if(expired || !FxInteger(f[1]))return false;long at=StringToInteger(f[1]);if(at<expires || at<last)return false;expired=true;last=at;return true;}
      if(n==8 && f[0]=="CHARGE")
      {
         if(!FxUuid(f[1]) || !FxHex(f[2],64) || (f[3]!="EURUSD" && f[3]!="USDJPY") ||
            !FxInteger(f[4]) || !FxInteger(f[5]) || !FxInteger(f[6]) || !FxInteger(f[7]))return false;
         long volume=StringToInteger(f[4]),risk=StringToInteger(f[5]),at=StringToInteger(f[6]),basis=StringToInteger(f[7]);
         int i=ArraySize(ids);long total=0;
         for(int k=0;k<i;k++){if(!closed[k])return false;total+=cents[k];}
         if(expired || i>=2 || Find(f[1])>=0 || volume<1 || volume>2000000 || risk<1 || risk>reference || basis<1 || basis>water || risk*10000>basis*entry_bps ||
            (total+risk)*10000>basis*total_bps || at<begins || at>=expires || at<last)return false;
         ArrayResize(ids,i+1);ArrayResize(hashes,i+1);ArrayResize(lots,i+1);
         ArrayResize(cents,i+1);ArrayResize(closed,i+1);
         ids[i]=f[1];hashes[i]=f[2];lots[i]=volume;cents[i]=risk;closed[i]=false;last=at;water=basis;
         return true;
      }
      if(n==5 && f[0]=="CLOSED")
      {
         int i=Find(f[1]);
         if(i<0 || closed[i] || !FxHex(f[2],64) || !FxInteger(f[3]) || !FxInteger(f[4]))return false;
         long at=StringToInteger(f[3]),filled=StringToInteger(f[4]);
         if(at<last || filled<1 || filled>lots[i])return false;
         closed[i]=true;last=at;return true;
      }
      return false;
   }
   bool Save(string row)
   {
      // Apply validates the prospective state; any persistence failure permanently
      // disables this instance. It can only reopen at a retained matching tip.
      if(!healthy || !Apply(row))return false;
      if(!journal.Append(row)){healthy=false;return false;}
      int n=ArraySize(rows);ArrayResize(rows,n+1);rows[n]=row;return true;
   }
public:
   DemoAcceptanceBudget(){healthy=false;}
   void Close(){journal.Close();healthy=false;}
   bool Healthy(){return healthy;}
   string Tip(){return healthy ? DgRowsTip(rows) : "";}
   int Charged(){return ArraySize(ids);}
   // Durable entry closure does not close the execution/protection journals.
   // No wall-clock claim is invented when a monotonic host deadline triggers it.
   bool Drain(){return healthy && (expired || Save("DRAIN"));}
   bool Draining(){return healthy && expired;}
   bool EntriesOpen(long now,long uncertainty)
   {return healthy && !expired && uncertainty>=0 && uncertainty<=100 && now-uncertainty>=begins && now+uncertainty<expires;}
   bool Open(string path,string account_scope,string release_hash,string policy_hash,string plan_hash,
             long start_ms,long expiry_ms,long reference_cents,int per_entry_rate,int total_rate,string account_currency,string equity_evidence,
             bool bootstrap,string retained_tip)
   {
      Close();ArrayResize(ids,0);ArrayResize(hashes,0);ArrayResize(lots,0);
      ArrayResize(cents,0);ArrayResize(closed,0);ArrayResize(rows,0);
      if(!FxHex(account_scope,64) || !FxHex(release_hash,64) || !FxHex(policy_hash,64) ||
         !FxHex(plan_hash,64) || !FxHex(equity_evidence,64) || equity_evidence==StringFormat("%064d",0) ||
         reference_cents<=0 || reference_cents>1000000000000 || per_entry_rate<1 || per_entry_rate>25 ||
         total_rate<per_entry_rate || total_rate>50 || (account_currency!="CAD" && account_currency!="USD") || start_ms<=0 || expiry_ms<=start_ms || expiry_ms-start_ms>300000 ||
         (bootstrap ? (FileIsExist(path) || retained_tip!="") :
          (!FileIsExist(path) || !FxHex(retained_tip,64))))return false;
      reference=reference_cents;water=reference;entry_bps=per_entry_rate;total_bps=total_rate;currency=account_currency;
      expired=false;scope=account_scope;release=release_hash;policy=policy_hash;begins=start_ms;expires=expiry_ms;last=begins;
      binding="DEMO_BUDGET_PERCENT_2\t"+scope+"\t"+release+"\t"+policy+"\t"+plan_hash+"\t"+
         IntegerToString(begins)+"\t"+IntegerToString(expires)+"\t"+currency+"\t2\t2000000\t"+IntegerToString(reference)+"\t"+
         IntegerToString(entry_bps)+"\t"+IntegerToString(total_bps)+"\t"+equity_evidence;
      if(!journal.Open(path,rows))return false;
      if(bootstrap)
      {if(!journal.Append(binding)){Close();return false;}ArrayResize(rows,1);rows[0]=binding;healthy=true;return true;}
      if(ArraySize(rows)<1 || ArraySize(rows)>6 || rows[0]!=binding || DgRowsTip(rows)!=retained_tip){Close();return false;}
      for(int i=1;i<ArraySize(rows);i++)if(!Apply(rows[i])){Close();return false;}
      healthy=true;return true;
   }
   bool Charge(const FxWork &w,long now,bool flat,long eligible_equity_cents)
   {
      if(!healthy || !flat || w.action!="ENTER" || w.environment!="PAPER" || w.venue!="BROKER_DEMO" ||
         FxScope(w)!=scope || w.release!=release || w.policy!=policy || w.currency!=currency ||
         !MathIsValidNumber(w.max_risk) || w.max_risk<=0 || w.max_risk>(double)reference/100.0 || eligible_equity_cents<=0 || eligible_equity_cents>1000000000000)return false;
      if(now>=expires && !expired){if(!Save("EXPIRED\t"+IntegerToString(now)))healthy=false;return false;}
      if(expired)return false;
      long risk=(long)MathCeil(w.max_risk*100.0);
      return Save("CHARGE\t"+w.id+"\t"+w.digest+"\t"+w.symbol+"\t"+IntegerToString(w.volume)+"\t"+
         IntegerToString(risk)+"\t"+IntegerToString(now)+"\t"+IntegerToString((long)MathMin(water,eligible_equity_cents)));
   }
   bool ConfirmClosed(const FxEntry &e,long now,string witness,bool positive_query,bool flat)
   {
      int i=Find(e.work.id);
      if(!healthy || !positive_query || !flat || i<0 || e.work.digest!=hashes[i] ||
         e.state!="CLOSED" || e.open_volume!=0 || e.remaining!=0)return false;
      // Positive deal reconciliation, never an empty position query. The backend
      // separately requires its independent audit before publishing another entry.
      return Save("CLOSED\t"+e.work.id+"\t"+witness+"\t"+IntegerToString(now)+"\t"+IntegerToString(e.filled));
   }
};
bool DemoEntryWindowOpen(DemoAcceptanceBudget &cap,long utc,int error,ulong mono,ulong deadline)
{return deadline>0 && mono<deadline && cap.EntriesOpen(utc,error);}
#endif
