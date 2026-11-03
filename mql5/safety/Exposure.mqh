#ifndef FX_SAFETY_EXPOSURE
#define FX_SAFETY_EXPOSURE
struct SPosition
{
   string scope,id,reservation,symbol,side;
   double volume,liquidation,stop,contract,base_rate,quote_rate,exit_cost,margin;
   bool owned;
};
struct SReservation
{
   string scope,id,symbol,side;
   double authorized,filled,pending,risk,base,counter,margin;
   bool final_order,unknown;
};
struct SExposure
{
   double risk,gross,margin,eur,usd,jpy;
   int flags,slots;
};
void SLegs(SExposure &a,string symbol,string side,double base,double counter)
{
   int sign=(side=="BUY" ? 1 : -1);
   if(symbol=="EURUSD") { a.eur+=sign*base; a.usd-=sign*counter; }
   else { a.usd+=sign*base; a.jpy-=sign*counter; }
}
void SSlot(string &slots[],string key)
{
   for(int i=0;i<ArraySize(slots);i++) if(slots[i]==key) return;
   int n=ArraySize(slots); ArrayResize(slots,n+1); slots[n]=key;
}
bool SAggregate(string scope,SPosition &positions[],SReservation &reserves[],SExposure &a)
{
   ZeroMemory(a); string slots[];
   for(int i=0;i<ArraySize(reserves);i++) for(int j=0;j<i;j++) if(reserves[i].id==reserves[j].id) return false;
   for(int i=0;i<ArraySize(positions);i++)
   {
      SPosition p=positions[i];
      if(p.scope!=scope || p.volume<=0) return false;
      for(int j=0;j<i;j++) if(positions[j].id==p.id) return false;
      if(!p.owned) a.flags|=32;
      if(p.stop<=0) a.flags|=8;
      else a.risk+=(MathMax(0,p.side=="BUY" ? p.liquidation-p.stop : p.stop-p.liquidation)*p.contract*p.quote_rate+p.exit_cost)*p.volume;
      double b=p.volume*p.contract*p.base_rate,q=p.volume*p.contract*p.liquidation*p.quote_rate;
      a.gross+=b; a.margin+=p.margin; SLegs(a,p.symbol,p.side,b,q);
      SSlot(slots,p.reservation=="" ? "p:"+p.id : "r:"+p.reservation);
      bool found=false; for(int j=0;j<ArraySize(reserves);j++) if(reserves[j].id==p.reservation) found=true;
      if(p.reservation!="" && !found) a.flags|=4;
   }
   for(int i=0;i<ArraySize(reserves);i++)
   {
      SReservation r=reserves[i];
      if(r.scope!=scope || r.filled+r.pending>r.authorized+1e-12) return false;
      double open=0;
      for(int j=0;j<ArraySize(positions);j++) if(positions[j].reservation==r.id)
      {
         if(positions[j].symbol!=r.symbol || positions[j].side!=r.side) return false;
         open+=positions[j].volume;
      }
      if(open>r.filled+1e-12) return false;
      double remaining=(r.final_order ? r.pending : MathMax(r.pending,r.authorized-r.filled));
      if(r.unknown) a.flags|=4;
      a.risk+=remaining*r.risk; a.gross+=remaining*r.base; a.margin+=remaining*r.margin;
      SLegs(a,r.symbol,r.side,remaining*r.base,remaining*r.counter);
      if(remaining>0) SSlot(slots,"r:"+r.id);
   }
   a.slots=ArraySize(slots); return true;
}
#endif
