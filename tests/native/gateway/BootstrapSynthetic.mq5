// Build synthetic local history in the dedicated validation terminal only.
#property strict
#property service
bool FxSetupCheck(const string label,const bool ok)
{
   if(!ok) Print("FX_M2B_SETUP_FAILED ",label," error=",GetLastError());
   return ok;
}

int FxBootstrapSynthetic()
{
   string path=TerminalInfoString(TERMINAL_DATA_PATH);
   if(StringFind(path,"\\fx-talanta\\.local\\m2b-native-")<0) return INIT_FAILED;
   string symbol="FXT_EURUSD";
   bool custom=false;
   if(!SymbolExist(symbol,custom) && !CustomSymbolCreate(symbol,"FXTalanta")) return INIT_FAILED;
   if(SymbolExist(symbol,custom) && !custom) return INIT_FAILED;
   bool ok=true;
   ok=FxSetupCheck("SYMBOL_CURRENCY_BASE",CustomSymbolSetString(symbol,SYMBOL_CURRENCY_BASE,"EUR")) && ok;
   ok=FxSetupCheck("SYMBOL_CURRENCY_PROFIT",CustomSymbolSetString(symbol,SYMBOL_CURRENCY_PROFIT,"USD")) && ok;
   ok=FxSetupCheck("SYMBOL_CURRENCY_MARGIN",CustomSymbolSetString(symbol,SYMBOL_CURRENCY_MARGIN,"USD")) && ok;
   ok=FxSetupCheck("SYMBOL_DIGITS",CustomSymbolSetInteger(symbol,SYMBOL_DIGITS,5)) && ok;
   ok=FxSetupCheck("SYMBOL_TRADE_MODE",CustomSymbolSetInteger(symbol,SYMBOL_TRADE_MODE,SYMBOL_TRADE_MODE_FULL)) && ok;
   ok=FxSetupCheck("SYMBOL_TRADE_CALC_MODE",CustomSymbolSetInteger(symbol,SYMBOL_TRADE_CALC_MODE,SYMBOL_CALC_MODE_CFDLEVERAGE)) && ok;
   ok=FxSetupCheck("SYMBOL_TRADE_EXEMODE",CustomSymbolSetInteger(symbol,SYMBOL_TRADE_EXEMODE,SYMBOL_TRADE_EXECUTION_MARKET)) && ok;
   ok=FxSetupCheck("SYMBOL_FILLING_MODE",CustomSymbolSetInteger(symbol,SYMBOL_FILLING_MODE,SYMBOL_FILLING_FOK|SYMBOL_FILLING_IOC)) && ok;
   ok=FxSetupCheck("SYMBOL_ORDER_MODE",CustomSymbolSetInteger(symbol,SYMBOL_ORDER_MODE,SYMBOL_ORDER_MARKET|SYMBOL_ORDER_SL|SYMBOL_ORDER_TP|SYMBOL_ORDER_LIMIT)) && ok;
   ok=FxSetupCheck("SYMBOL_TRADE_STOPS_LEVEL",CustomSymbolSetInteger(symbol,SYMBOL_TRADE_STOPS_LEVEL,10)) && ok;
   ok=FxSetupCheck("SYMBOL_TRADE_FREEZE_LEVEL",CustomSymbolSetInteger(symbol,SYMBOL_TRADE_FREEZE_LEVEL,5)) && ok;
   ok=FxSetupCheck("SYMBOL_SPREAD",CustomSymbolSetInteger(symbol,SYMBOL_SPREAD,20)) && ok;
   ok=FxSetupCheck("SYMBOL_POINT",CustomSymbolSetDouble(symbol,SYMBOL_POINT,0.00001)) && ok;
   ok=FxSetupCheck("SYMBOL_TRADE_TICK_SIZE",CustomSymbolSetDouble(symbol,SYMBOL_TRADE_TICK_SIZE,0.00001)) && ok;
   ok=FxSetupCheck("SYMBOL_TRADE_CONTRACT_SIZE",CustomSymbolSetDouble(symbol,SYMBOL_TRADE_CONTRACT_SIZE,100000)) && ok;
   ok=FxSetupCheck("SYMBOL_VOLUME_MIN",CustomSymbolSetDouble(symbol,SYMBOL_VOLUME_MIN,0.01)) && ok;
   ok=FxSetupCheck("SYMBOL_VOLUME_MAX",CustomSymbolSetDouble(symbol,SYMBOL_VOLUME_MAX,1)) && ok;
   ok=FxSetupCheck("SYMBOL_VOLUME_STEP",CustomSymbolSetDouble(symbol,SYMBOL_VOLUME_STEP,0.01)) && ok;
   ok=FxSetupCheck("SYMBOL_MARGIN_INITIAL",CustomSymbolSetDouble(symbol,SYMBOL_MARGIN_INITIAL,1000)) && ok;
   for(int d=1;d<=5;d++)
   {
      ok=CustomSymbolSetSessionQuote(symbol,(ENUM_DAY_OF_WEEK)d,0,0,86399) && ok;
      ok=CustomSymbolSetSessionTrade(symbol,(ENUM_DAY_OF_WEEK)d,0,0,86399) && ok;
   }
   MqlRates rates[]; ArrayResize(rates,7200);
   for(int i=0;i<7200;i++)
   {
      rates[i].time=D'2026.01.01'+i*60;
      rates[i].open=1.1000; rates[i].high=1.1001; rates[i].low=1.0999; rates[i].close=1.1000;
      rates[i].tick_volume=60; rates[i].real_volume=0; rates[i].spread=20;
   }
   int bars=CustomRatesReplace(symbol,rates[0].time,rates[7199].time,rates);
   ok=bars==7200 && ok;
   ok=SymbolSelect(symbol,true) && ok;
   Print("FX_M2B_SYNTHETIC_BOOTSTRAP bars=",bars," success=",ok," error=",GetLastError());
   return ok ? INIT_SUCCEEDED : INIT_FAILED;
}
void OnStart(){ Print("FX_M2B_SERVICE_RESULT ",FxBootstrapSynthetic()); }
