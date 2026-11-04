// M2A fixture-only source. NOT the execution EA; NOT native-qualified.
// Inputs: Python export of reviewed JSON vectors, WITHOUT expected outputs.
// This script performs no account, symbol, network or trading operations.
#property strict
#property script_show_inputs
input bool RunRisk=true;

bool ReadRow(int handle,int count,string &row[])
{
   if(FileIsEnding(handle)) return false;
   ArrayResize(row,count);
   for(int i=0;i<count;i++)
   {
      if(FileIsEnding(handle) || (i>0 && FileIsLineEnding(handle))) return false;
      row[i]=FileReadString(handle);
   }
   return FileIsLineEnding(handle) || FileIsEnding(handle);
}

string Risk(string &r[],double &lots,double &risk,double &gross,double &margin,double &perlot)
{
   // r[0]=case id; subsequent positions follow RiskVector field declaration.
   if(r[6]=="" || r[7]=="" || r[8]=="") return "CONVERSION_MISSING";
   double v[28];
   for(int i=3;i<28;i++) v[i]=StringToDouble(r[i]);
   if(v[9]<0 || v[9]>2) return "CONVERSION_STALE";
   if((r[1]!="EURUSD" && r[1]!="USDJPY") || (r[2]!="USD" && r[2]!="CAD")) return "UNSUPPORTED";
   if(r[2]=="USD" && v[6]!=1) return "CONVERSION_INCONSISTENT";
   if(v[3]<=0 || v[6]<=0) return "INVALID_SPECIFICATION";
   double b=(r[1]=="EURUSD" ? v[3]*v[6] : v[6]);
   double q=(r[1]=="EURUSD" ? v[6] : v[6]/v[3]);
   if(MathAbs(v[7]-b)>1e-12 || MathAbs(v[8]-q)>1e-12) return "CONVERSION_INCONSISTENT";
   if(!(v[5]<v[3] && v[3]<=v[4]) || v[16]<=0 || v[15]<=0 || v[15]>v[17] || MathAbs(v[15]/v[16]-MathRound(v[15]/v[16]))>1e-9) return "INVALID_SPECIFICATION";
   if(v[27]==0) return "UNKNOWN_CASHFLOW";
   if(v[26]!=0 || v[10]<=v[25]*0.95) return "LOSS_BLOCK";
   double eligible=MathMin(v[10],v[11]);
   perlot=(v[4]-v[5])*100000*v[8]+2*v[12]+v[13]+v[14];
   double base=100000*v[7],quote=100000*v[4]*v[8];
   double charge=(v[4]-v[3])*100000*v[8]+v[12];
   double upper=v[17];
   upper=MathMin(upper,eligible*0.0025/(perlot+0.0025*charge));
   upper=MathMin(upper,(eligible*0.005-v[18])/(perlot+0.005*charge));
   upper=MathMin(upper,(v[23]*0.01-v[24]-v[18])/perlot);
   upper=MathMin(upper,(eligible*2-v[19])/(base+2*charge));
   upper=MathMin(upper,(eligible*0.20-v[20])/(base*0.02+0.20*charge));
   double cap=MathMax(0,eligible-MathMax(0,upper)*charge),lower=0;
   for(int j=0;j<2;j++)
   {
      double leg=(j==0 ? base : -quote),existing=(j==0 ? v[21] : v[22]);
      double a=(-cap-existing)/leg,z=(cap-existing)/leg;
      lower=MathMax(lower,MathMin(a,z)); upper=MathMin(upper,MathMax(a,z));
   }
   lots=MathFloor(upper/v[16])*v[16]; // Never round upward to obtain eligibility.
   if(lots<MathMax(v[15],lower)) return "MINIMUM_LOT";
   risk=lots*perlot; gross=lots*base; margin=gross*0.02;
   return "ACCEPTED";
}

void OnStart()
{
   string name=(RunRisk ? "risk" : "replay");
   int source=FileOpen(name+".tsv",FILE_READ|FILE_CSV|FILE_ANSI,'\t',CP_UTF8);
   if(source==INVALID_HANDLE) { Print("INPUT_UNAVAILABLE"); return; }
   int output=FileOpen(name+"-native.tsv",FILE_WRITE|FILE_CSV|FILE_ANSI,'\t',CP_UTF8);
   if(output==INVALID_HANDLE) { FileClose(source); Print("OUTPUT_UNAVAILABLE"); return; }
   string row[],ids[],hashes[],outcomes[];
   int count=(RunRisk ? 28 : 8),seen=0;
   if(!ReadRow(source,count,row)) { FileClose(source); FileClose(output); Print("INVALID_HEADER"); return; }
   FileWrite(output,"id","reason","volume","risk","gross","margin","risk_per_lot");
   while(!FileIsEnding(source))
   {
      if(!ReadRow(source,count,row)) { Print("INVALID_ROW"); break; }
      string reason="ACCEPTED";
      double lots=0,risk=0,gross=0,margin=0,perlot=0;
      if(RunRisk) reason=Risk(row,lots,risk,gross,margin,perlot);
      else
      {
         int prior=-1;
         for(int i=0;i<seen;i++) if(ids[i]==row[1]) prior=i;
         if(row[5]!="ea-protocol/1") reason="UNSUPPORTED";
         else if(row[4]!="fixture-usd") reason="ACCOUNT_MISMATCH";
         else if(prior>=0) reason=(hashes[prior]==row[2] ? (outcomes[prior]=="ACCEPTED" ? "REPLAY" : "REPLAY_"+outcomes[prior]) : "HASH_CONFLICT");
         else if((int)StringToInteger(row[3])!=seen+1) reason="SEQUENCE_GAP";
         else
         {
            if(StringToDouble(row[6])<=StringToDouble(row[7])) reason="EXPIRED";
            ArrayResize(ids,seen+1); ArrayResize(hashes,seen+1); ArrayResize(outcomes,seen+1);
            ids[seen]=row[1]; hashes[seen]=row[2]; outcomes[seen]=reason; seen++;
         }
      }
      FileWrite(output,row[0],reason,DoubleToString(lots,6),DoubleToString(risk,6),DoubleToString(gross,6),DoubleToString(margin,6),DoubleToString(perlot,6));
   }
   FileClose(source); FileClose(output);
}
