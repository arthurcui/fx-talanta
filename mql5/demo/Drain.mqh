#ifndef FX_DEMO_DRAIN
#define FX_DEMO_DRAIN
#include "Reconcile.mqh"
// Positive reconciliation plus flatness, never an empty position query alone.
// A stopped network is not a successful shutdown: unsent outbox evidence remains.
bool DemoDrainComplete(FxGateway &gateway,DemoReconciler &scan,
                       bool complete_query,bool connected,bool flat,
                       bool protection_unresolved,bool pending_report)
{
   if(!complete_query || !connected || !flat || protection_unresolved || pending_report)return false;
   for(int i=0;i<gateway.Count();i++)
   {
      FxEntry e=gateway.At(i);
      if(e.open_volume!=0 || e.remaining!=0)return false;
      if(e.state=="REJECTED")continue; // Durable, definite no-call refusal.
      if(e.state!="CLOSED" || !scan.Confirmed(i))return false;
   }
   return true;
}
#endif
