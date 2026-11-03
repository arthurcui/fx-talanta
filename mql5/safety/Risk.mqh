// Independent M2C arithmetic. No trade, account, transport or terminal calls.
// The input is a validated reconciled snapshot, not a model or work override.
#ifndef FX_SAFETY_RISK
#define FX_SAFETY_RISK
double SUp(double x) { return MathCeil((x+0.0000001)*1e6)/1e6; }
double SDown(double x) { return MathFloor((x-0.0000001)*1e6)/1e6; }
string SText(string &keys[],string &r[],string name)
{
   for(int i=0;i<ArraySize(keys);i++) if(keys[i]==name) return r[i];
   return "~";
}
double SV(string &k[],string &r[],string n) { return StringToDouble(SText(k,r,n)); }
bool SGrid(double x,double step) { return MathAbs(x/step-MathRound(x/step))<1e-7; }
string SState(int flags)
{
   if((flags&1)!=0) return "HARD_HALT";
   if((flags&2)!=0) return "LOSS_PAUSE";
   if((flags&4)!=0) return "OUTCOME_UNKNOWN";
   if((flags&8)!=0) return "PROTECTION_PENDING";
   if((flags&16)!=0) return "STARTUP_RECONCILE";
   if((flags&32)!=0) return "DEGRADED_PROTECT";
   if((flags&64)!=0) return "OWNER_PAUSED";
   return "";
}
string SRisk(string &k[],string &r[],double &volume,double &loss,double &gross_out,double &margin_out)
{
   volume=0; loss=0; gross_out=0; margin_out=0;
   string symbol=SText(k,r,"symbol"),currency=SText(k,r,"currency"),side=SText(k,r,"side");
   if((symbol!="EURUSD" && symbol!="USDJPY") || (currency!="USD" && currency!="CAD") || (side!="BUY" && side!="SELL")) return "INVALID_SPECIFICATION";
   string state=SState((int)SV(k,r,"flags")); if(state!="") return state;
   if(SV(k,r,"cashflows_known")==0) return "UNKNOWN_CASHFLOW";
   if(SV(k,r,"inputs_ok")==0) return "REQUIRED_INPUTS";
   if(SV(k,r,"blackout")!=0 || SV(k,r,"session_open")==0) return "BLACKOUT_OR_SESSION";
   double error=SV(k,r,"clock_error_ms"),age=SV(k,r,"quote_age_ms"),conversion=SV(k,r,"conversion_age_ms");
   if(error>100) return "CLOCK_UNVERIFIED";
   if(SV(k,r,"expires_in_ms")<=error) return "EXPIRED";
   if(age<error || age>2000-error) return "QUOTE_STALE";
   if(conversion<error || conversion>2000-error) return "CONVERSION_STALE";
   double usd=SV(k,r,"usd_to_account"),br=SV(k,r,"base_to_account"),qr=SV(k,r,"quote_to_account"),cr=SV(k,r,"cost_to_account");
   if(usd<=0 || br<=0 || qr<=0 || cr<=0) return "CONVERSION_MISSING";
   double bid=SV(k,r,"bid"),ask=SV(k,r,"ask"),stop=SV(k,r,"stop");
   string cc=SText(k,r,"commission_currency");
   if(bid<=0 || ask<=0 || stop<=0) return "INVALID_SPECIFICATION";
   double expected_base=(symbol=="EURUSD" ? bid*usd : usd),expected_quote=(symbol=="EURUSD" ? usd : usd/bid);
   if((currency=="USD" && (usd!=1 || cc!="USD")) || (cc!="USD" && cc!="CAD") || MathAbs(br-expected_base)>1e-12 || MathAbs(qr-expected_quote)>1e-12 || cr!=(cc=="USD" ? usd : 1)) return "CONVERSION_INCONSISTENT";
   bool buy=side=="BUY";
   double price=(buy ? ask : bid),minimum=SV(k,r,"minimum"),step=SV(k,r,"step"),maximum=SV(k,r,"maximum"),tick=SV(k,r,"tick_size");
   if(bid>ask || !(buy ? stop<bid : stop>ask) || minimum<=0 || step<1e-8 || tick<=0 || minimum>maximum || maximum/step>1000000 || !SGrid(minimum,step) || !SGrid(step,1e-8) || !SGrid(stop,tick)) return "INVALID_SPECIFICATION";
   double adverse=(buy ? price-SV(k,r,"benchmark") : SV(k,r,"benchmark")-price);
   // Compare price costs on the explicit 1e-8 price grid, avoiding subtraction ULPs.
   if(MathRound((ask-bid)*1e8)>MathRound(SV(k,r,"maximum_spread")*1e8) || MathRound(adverse*1e8)>MathRound(SV(k,r,"maximum_adverse")*1e8)) return "COST_LIMIT";
   if(SV(k,r,"occupied_slots")>=2 || SV(k,r,"symbol_occupied")!=0) return "POSITION_LIMIT";
   double day=SV(k,r,"day_start"),dl=SV(k,r,"day_loss");
   if(dl>=day*0.01) return "LOSS_PAUSE";
   double distance=MathAbs(price-stop),contract=SV(k,r,"contract"),commission=SV(k,r,"commission");
   double risk=SUp(MathMax(MathMax(distance*contract*qr,distance/tick*SV(k,r,"tick_value_loss")),SV(k,r,"broker_loss_per_lot"))+(2*commission+SV(k,r,"slippage")+SV(k,r,"financing"))*cr);
   double base=SUp(contract*br),counter=SUp(contract*price*qr),charge=SUp((ask-bid)*contract*qr+commission*cr),margin=SUp(SV(k,r,"broker_margin_per_lot"));
   if(MathMax(MathMax(risk,base),MathMax(MathMax(counter,charge),margin))>100000000) return "ARITHMETIC_RANGE";
   double eligible=MathMin(SV(k,r,"equity"),SV(k,r,"capital"));
   double upper=MathMin(maximum,SV(k,r,"request_volume"));
   upper=MathMin(upper,eligible*0.0025/risk); upper=MathMin(upper,SV(k,r,"request_risk")/risk);
   upper=MathMin(upper,eligible*2/base); upper=MathMin(upper,eligible*0.20/margin);
   int first=(int)MathFloor(upper/step),last=(int)MathRound(minimum/step),sign=(buy ? 1 : -1);
   for(int n=first;n>=last;n--)
   {
      if(first-n>=4096) return "COMPUTE_BUDGET";
      double lots=n*step,rl=SUp(lots*risk),g=SUp(lots*base),m=SUp(lots*margin),cap=SDown(eligible-SUp(lots*charge));
      double allrisk=SV(k,r,"existing_risk")+rl,allmargin=SV(k,r,"existing_margin")+m;
      if(rl<=SDown(cap*0.0025) && rl<=SV(k,r,"request_risk") && allrisk<=SDown(cap*0.005)
         && allrisk+dl<=SDown(day*0.01) && SV(k,r,"existing_gross")+g<=SDown(cap*2)
         && allmargin<=SDown(cap*0.20) && cap-MathMax(allrisk,SV(k,r,"stress_loss"))>SUp(allmargin*SV(k,r,"stopout_ratio"))
         && SUp(MathAbs(SV(k,r,"base_exposure")+sign*lots*contract*br))<=cap && SUp(MathAbs(SV(k,r,"quote_exposure")-sign*lots*contract*price*qr))<=cap && SV(k,r,"other_exposure")<=cap)
      { volume=lots; loss=rl; gross_out=g; margin_out=m; return "ACCEPTED"; }
   }
   return "MINIMUM_LOT";
}
#endif
