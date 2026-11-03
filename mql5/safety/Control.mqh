#ifndef FX_SAFETY_CONTROL
#define FX_SAFETY_CONTROL
struct SLoss
{
   int day;
   double start,flows,units,high,loss;
   bool paused,hard,owner;
};
bool SLossStep(SLoss &s,int day,double equity,double flow,double before,bool reconciled,double midnight)
{
   if(!reconciled || day<s.day || equity<=0) return false;
   SLoss next=s;
   if(flow!=0)
   {
      if(before<=0) return false;
      double nav=before/next.units;
      next.high=MathMax(next.high,nav); next.hard|=before<=next.high*next.units*0.95;
      next.units+=flow/nav; if(next.units<=0) return false;
   }
   double nav=equity/next.units;
   next.high=MathMax(next.high,nav); next.hard|=equity<=next.high*next.units*0.95;
   if(day>s.day)
   {
      if(midnight<=0 || flow!=0) return false;
      next.start=midnight; next.flows=0; next.paused=false;
   }
   else next.flows+=flow;
   next.loss=MathMax(0,next.start+next.flows-equity);
   next.paused|=next.loss>=next.start*0.01; next.day=day;
   s=next; return true;
}
struct SProtection
{
   string phase,boot;
   long submitted,repair,exit,last;
   bool hard;
};
string SProtect(SProtection &p,long now,string boot,bool storage,bool broker,bool reconciled,bool protected_ok,bool closed,bool unknown,bool rejected=false)
{
   if(p.repair<=p.submitted || p.exit<=p.repair) return "INVALID_DEADLINES";
   if(!storage) return "ALERT_STORAGE_NO_MUTATION";
   if(boot!=p.boot || now<p.last || now<p.submitted) { p.hard=true; return "RECONCILE_CLOCK_NO_MUTATION"; }
   bool settled=((p.phase=="PROTECTED" && protected_ok) || (p.phase=="CLOSED" && closed)) && reconciled;
   p.last=now; p.hard|=!settled && now>=p.exit;
   if(p.phase=="CLOSED" && !closed) { p.hard=true; return "RECONCILE_NO_RESEND"; }
   if(p.phase=="EXIT_REJECTED" || (rejected && reconciled && p.phase=="EXITING"))
   { p.phase="EXIT_REJECTED"; p.hard=true; return "ALERT_EXIT_REJECTED"; }
   if(rejected && reconciled && p.phase=="REPAIRING") p.phase="REPAIR_REJECTED";
   if((unknown || p.phase=="UNKNOWN") && (!reconciled || (!closed && !protected_ok)))
   { p.phase="UNKNOWN"; return "RECONCILE_NO_RESEND"; }
   if(reconciled && closed) { p.phase="CLOSED"; return "CLOSED_CONFIRMED"; }
   if(reconciled && protected_ok) { p.phase="PROTECTED"; return "PROTECTED_CONFIRMED"; }
   if(!reconciled || !broker) return "ALERT_UNRESOLVED_NO_MUTATION";
   if(p.phase=="REPAIRING" || p.phase=="EXITING") { p.phase="UNKNOWN"; return "RECONCILE_NO_RESEND"; }
   if(now>=p.repair || p.phase=="REPAIR_REJECTED") { p.phase="EXITING"; return "CONTROLLED_EXIT_ONCE"; }
   p.phase="REPAIRING"; return "ATTACH_STOP_ONCE";
}
#endif
