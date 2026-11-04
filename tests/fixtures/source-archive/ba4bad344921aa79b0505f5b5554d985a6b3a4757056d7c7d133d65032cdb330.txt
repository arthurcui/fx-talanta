#ifndef FX_DEMO_ACTIVATION
#define FX_DEMO_ACTIVATION
#include "../gateway/Wire.mqh"
class DemoActivationPermit
{
private:
   bool armed;
public:
   DemoActivationPermit(){armed=false;}
   bool Armed(){return armed;}
   bool Load(string text,string expected_hash,string scope,string release,string policy,string budget,
             long begins,long expires,long offset,long evidence_until)
   {
      armed=false;string f[];
      if(!FxHex(expected_hash,64) || FxHash(text)!=expected_hash || StringLen(text)>2048 ||
         StringSplit(text,'\t',f)!=11 || f[0]!="BOUNDED_DEMO_ACTIVATION_1" ||
         f[1]!=scope || f[2]!=release || f[3]!=policy || f[4]!=budget)return false;
      for(int i=1;i<=6;i++)if(!FxHex(f[i],64) || f[i]==StringFormat("%064d",0))return false;
      if(!FxInteger(f[7]) || !FxInteger(f[8]) || !FxInteger(f[10]) ||
         f[9]!=IntegerToString(offset) || MathAbs(offset)>50400000 ||
         StringToInteger(f[7])!=begins || StringToInteger(f[8])!=expires ||
         StringToInteger(f[10])!=evidence_until || begins<=0 || expires<=begins || expires-begins>300000 ||
         evidence_until<expires+60000 || evidence_until-begins>900000)return false;
      armed=true;return true;
   }
};
#endif
