//+------------------------------------------------------------------+
//|                                         实盘下单工具看板.mq5      |
//|  复刻：一键平仓 / 减仓 / 平多空盈亏 / 保本 / 删挂单 / 挂多挂空     |
//+------------------------------------------------------------------+
#property copyright "IgniteQuant"
#property link      ""
#property version   "1.00"
#property description "实盘手工下单看板：平仓/减仓/保本/挂单管理/市价开仓"

#include <Trade/Trade.mqh>

input long   InpMagic          = 0;      // Magic(0=管理本品种全部持仓)
input int    InpSlippagePoints = 30;     // 滑点(点)
input int    InpPanelX         = 12;     // 面板左边距
input int    InpPanelY         = 28;     // 面板上边距
input bool   InpOnlyChartSymbol = true;  // 仅操作当前图表品种

CTrade trade;

string PREFIX = "LTP_";
int    g_btn_w = 168;
int    g_half_w = 80;
int    g_btn_h = 26;
int    g_gap = 4;
color  CLR_BG      = C'42,42,42';
color  CLR_BTN     = C'72,72,72';
color  CLR_BTN_TXT = clrWhite;
color  CLR_GREEN   = C'0,170,80';
color  CLR_RED     = C'200,50,50';
color  CLR_EDIT_BG = C'55,55,55';
color  CLR_EDIT_FG = C'0,220,90';
color  CLR_HEADER  = C'55,55,55';

//+------------------------------------------------------------------+
bool MatchMagic(const long magic)
  {
   if(InpMagic == 0)
      return true;
   return magic == InpMagic;
  }

//+------------------------------------------------------------------+
bool MatchSymbol(const string sym)
  {
   if(!InpOnlyChartSymbol)
      return true;
   return sym == _Symbol;
  }

//+------------------------------------------------------------------+
double NormalizeVol(const double volume)
  {
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0)
      step = 0.01;
   double v = MathFloor(volume / step + 1e-8) * step;
   if(v < vmin)
      return 0.0;
   if(v > vmax)
      v = vmax;
   int digits = 0;
   double t = step;
   while(t < 1.0 - 1e-12 && digits < 8)
     {
      t *= 10.0;
      digits++;
     }
   return NormalizeDouble(v, digits);
  }

//+------------------------------------------------------------------+
double ReadEdit(const string name, const double fallback)
  {
   string s = ObjectGetString(0, name, OBJPROP_TEXT);
   StringReplace(s, " ", "");
   if(s == "")
      return fallback;
   double v = StringToDouble(s);
   if(v < 0.0)
      return fallback;
   return v;
  }

//+------------------------------------------------------------------+
void SetEdit(const string name, const string text)
  {
   ObjectSetString(0, name, OBJPROP_TEXT, text);
  }

//+------------------------------------------------------------------+
double FloatingProfit()
  {
   double profit = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; --i)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(!MatchSymbol(PositionGetString(POSITION_SYMBOL)))
         continue;
      if(!MatchMagic(PositionGetInteger(POSITION_MAGIC)))
         continue;
      profit += PositionGetDouble(POSITION_PROFIT)
                + PositionGetDouble(POSITION_SWAP);
     }
   return profit;
  }

//+------------------------------------------------------------------+
bool TradeReady()
  {
   // 1) 工具栏「算法交易」总开关
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
     {
      Alert("未开启：工具栏「算法交易」按钮（需变成绿色/按下）\n"
            "位置：MT5 顶部工具栏，Algo Trading / 自动交易");
      return false;
     }
   // 2) 本 EA 属性里的「允许算法交易」
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
     {
      Alert("未勾选：EA 属性 →「常用」→「允许算法交易」\n"
            "操作：图表空白处右键 → 专家列表 → 选中本看板 → 属性 → 勾选后确定\n"
            "或：卸下后重新拖入，在弹出窗口「常用」页勾选");
      return false;
     }
   // 3) 账户侧是否允许交易（只读账户/禁用专家时会失败）
   if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))
     {
      Alert("当前账户不允许交易（可能是只读/投资者密码登录）");
      return false;
     }
   if(!AccountInfoInteger(ACCOUNT_TRADE_EXPERT))
     {
      Alert("经纪商禁止此账户使用 EA 自动交易，请联系经纪商或换账户");
      return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
void ClosePositionTicket(const ulong ticket, const double volume = 0.0)
  {
   if(!PositionSelectByTicket(ticket))
      return;
   string sym = PositionGetString(POSITION_SYMBOL);
   double vol = PositionGetDouble(POSITION_VOLUME);
   long type = PositionGetInteger(POSITION_TYPE);
   if(volume > 0.0)
      vol = NormalizeVol(volume);
   else
      vol = NormalizeVol(vol);
   if(vol <= 0.0)
      return;

   MqlTradeRequest req;
   MqlTradeResult  res;
   ZeroMemory(req);
   ZeroMemory(res);
   req.action    = TRADE_ACTION_DEAL;
   req.position  = ticket;
   req.symbol    = sym;
   req.volume    = vol;
   req.deviation = InpSlippagePoints;
   req.magic     = (InpMagic == 0 ? (long)PositionGetInteger(POSITION_MAGIC) : InpMagic);
   if(type == POSITION_TYPE_BUY)
     {
      req.type = ORDER_TYPE_SELL;
      req.price = SymbolInfoDouble(sym, SYMBOL_BID);
     }
   else
     {
      req.type = ORDER_TYPE_BUY;
      req.price = SymbolInfoDouble(sym, SYMBOL_ASK);
     }
   if(!OrderSend(req, res))
      PrintFormat("平仓失败 ticket=%I64u retcode=%u %s", ticket, res.retcode, res.comment);
  }

//+------------------------------------------------------------------+
enum ENUM_CLOSE_FILTER
  {
   CLOSE_ALL = 0,
   CLOSE_BUY,
   CLOSE_SELL,
   CLOSE_PROFIT,
   CLOSE_LOSS,
   CLOSE_PARTIAL
  };

//+------------------------------------------------------------------+
void CloseByFilter(const ENUM_CLOSE_FILTER filter, const double ratio = 1.0)
  {
   if(!TradeReady())
      return;

   for(int i = PositionsTotal() - 1; i >= 0; --i)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(!MatchSymbol(PositionGetString(POSITION_SYMBOL)))
         continue;
      if(!MatchMagic(PositionGetInteger(POSITION_MAGIC)))
         continue;

      long type = PositionGetInteger(POSITION_TYPE);
      double p = PositionGetDouble(POSITION_PROFIT)
                 + PositionGetDouble(POSITION_SWAP);
      double vol = PositionGetDouble(POSITION_VOLUME);

      bool ok = false;
      double close_vol = vol;
      switch(filter)
        {
         case CLOSE_ALL:    ok = true; break;
         case CLOSE_BUY:    ok = (type == POSITION_TYPE_BUY); break;
         case CLOSE_SELL:   ok = (type == POSITION_TYPE_SELL); break;
         case CLOSE_PROFIT: ok = (p > 0.0); break;
         case CLOSE_LOSS:   ok = (p < 0.0); break;
         case CLOSE_PARTIAL:
            ok = true;
            close_vol = NormalizeVol(vol * ratio);
            if(close_vol <= 0.0 || close_vol >= vol)
              {
               // 无法按比例减仓时，手数过小则跳过；比例接近全平则全平
               if(ratio >= 0.99)
                  close_vol = vol;
               else
                  ok = false;
              }
            break;
        }
      if(!ok)
         continue;
      if(filter == CLOSE_PARTIAL)
         ClosePositionTicket(ticket, close_vol);
      else
         ClosePositionTicket(ticket, 0.0);
     }
  }

//+------------------------------------------------------------------+
void BreakEvenAll()
  {
   if(!TradeReady())
      return;

   int offset_pts = (int)MathRound(ReadEdit(PREFIX + "BE_OFF", 0.0));
   int done = 0;

   for(int i = PositionsTotal() - 1; i >= 0; --i)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      if(!MatchSymbol(sym))
         continue;
      if(!MatchMagic(PositionGetInteger(POSITION_MAGIC)))
         continue;

      double profit = PositionGetDouble(POSITION_PROFIT)
                      + PositionGetDouble(POSITION_SWAP);
      if(profit <= 0.0)
         continue;

      double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
      double tp = PositionGetDouble(POSITION_TP);
      double sl = PositionGetDouble(POSITION_SL);
      double point = SymbolInfoDouble(sym, SYMBOL_POINT);
      int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      long type = PositionGetInteger(POSITION_TYPE);

      double new_sl = 0.0;
      if(type == POSITION_TYPE_BUY)
         new_sl = NormalizeDouble(open_price + offset_pts * point, digits);
      else
         new_sl = NormalizeDouble(open_price - offset_pts * point, digits);

      // 只朝有利方向改：多单新SL不能低于旧SL；空单不能高于旧SL
      if(type == POSITION_TYPE_BUY)
        {
         if(sl > 0.0 && new_sl <= sl)
            continue;
         double bid = SymbolInfoDouble(sym, SYMBOL_BID);
         if(new_sl >= bid)
            continue;
        }
      else
        {
         if(sl > 0.0 && new_sl >= sl)
            continue;
         double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
         if(new_sl <= ask)
            continue;
        }

      trade.SetExpertMagicNumber((ulong)PositionGetInteger(POSITION_MAGIC));
      trade.SetDeviationInPoints(InpSlippagePoints);
      if(trade.PositionModify(ticket, new_sl, tp))
         done++;
      else
         PrintFormat("保本失败 ticket=%I64u err=%d", ticket, GetLastError());
     }

   if(done > 0)
      PlaySound("ok.wav");
   else
      Print("一键保本：没有可保护的盈利持仓");
  }

//+------------------------------------------------------------------+
void DeleteAllPendings()
  {
   if(!TradeReady())
      return;
   for(int i = OrdersTotal() - 1; i >= 0; --i)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0)
         continue;
      if(!OrderSelect(ticket))
         continue;
      if(!MatchSymbol(OrderGetString(ORDER_SYMBOL)))
         continue;
      if(!MatchMagic(OrderGetInteger(ORDER_MAGIC)))
         continue;
      trade.SetExpertMagicNumber((ulong)OrderGetInteger(ORDER_MAGIC));
      if(!trade.OrderDelete(ticket))
         PrintFormat("删挂单失败 ticket=%I64u err=%d", ticket, GetLastError());
     }
  }

//+------------------------------------------------------------------+
void OpenMarket(const bool is_buy)
  {
   if(!TradeReady())
      return;

   double lots = NormalizeVol(ReadEdit(PREFIX + "LOTS", 0.1));
   if(lots <= 0.0)
     {
      Alert("手数无效");
      return;
     }
   int sl_pts = (int)MathRound(ReadEdit(PREFIX + "SL", 0.0));
   int tp_pts = (int)MathRound(ReadEdit(PREFIX + "TP", 0.0));

   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double price = is_buy ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                         : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl = 0.0, tp = 0.0;
   if(sl_pts > 0)
      sl = NormalizeDouble(is_buy ? price - sl_pts * point : price + sl_pts * point, digits);
   if(tp_pts > 0)
      tp = NormalizeDouble(is_buy ? price + tp_pts * point : price - tp_pts * point, digits);

   trade.SetExpertMagicNumber((ulong)(InpMagic == 0 ? 20260718 : InpMagic));
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(_Symbol);

   bool ok = is_buy ? trade.Buy(lots, _Symbol, 0.0, sl, tp, "看板挂多")
                    : trade.Sell(lots, _Symbol, 0.0, sl, tp, "看板挂空");
   if(!ok)
      PrintFormat("开仓失败 retcode=%u %s", trade.ResultRetcode(), trade.ResultComment());
  }

//+------------------------------------------------------------------+
void MakeRect(const string name, const int x, const int y, const int w, const int h, const color bg)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, C'30,30,30');
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER, 0);
  }

//+------------------------------------------------------------------+
void MakeButton(const string name, const string text, const int x, const int y,
                const int w, const int h, const color bg, const color fg = clrWhite)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, fg);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, C'40,40,40');
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
   ObjectSetString(0, name, OBJPROP_FONT, "Microsoft YaHei");
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER, 1);
   ObjectSetInteger(0, name, OBJPROP_STATE, false);
  }

//+------------------------------------------------------------------+
void MakeEdit(const string name, const string text, const int x, const int y,
              const int w, const int h)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_EDIT, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, CLR_EDIT_FG);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, CLR_EDIT_BG);
   ObjectSetInteger(0, name, OBJPROP_BORDER_COLOR, C'40,40,40');
   ObjectSetInteger(0, name, OBJPROP_ALIGN, ALIGN_CENTER);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
   ObjectSetString(0, name, OBJPROP_FONT, "Microsoft YaHei");
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, true);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER, 2);
  }

//+------------------------------------------------------------------+
void MakeLabel(const string name, const string text, const int x, const int y,
               const color fg = clrWhite, const int fontsize = 9)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, fg);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, fontsize);
   ObjectSetString(0, name, OBJPROP_FONT, "Microsoft YaHei");
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetInteger(0, name, OBJPROP_ZORDER, 1);
  }

//+------------------------------------------------------------------+
void BuildPanel()
  {
   int x = InpPanelX;
   int y = InpPanelY;
   int pad = 6;
   int row = y + pad;
   int panel_h = 360;

   MakeRect(PREFIX + "BG", x, y, g_btn_w + pad * 2, panel_h, CLR_BG);

   // 顶栏时间
   MakeRect(PREFIX + "HDR", x + pad, row, g_btn_w, 24, CLR_HEADER);
   MakeLabel(PREFIX + "TIME", TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS),
             x + pad + 22, row + 4, clrWhite, 9);
   MakeLabel(PREFIX + "DOT", "●", x + pad + 6, row + 4, clrWhite, 8);
   row += 24 + g_gap;

   MakeButton(PREFIX + "CLOSE_ALL", "一键平仓 0.00", x + pad, row, g_btn_w, g_btn_h, CLR_BTN);
   row += g_btn_h + g_gap;

   MakeButton(PREFIX + "CUT50", "减仓 50%", x + pad, row, g_half_w, g_btn_h, CLR_BTN);
   MakeButton(PREFIX + "CUT80", "减仓 80%", x + pad + g_half_w + 8, row, g_half_w, g_btn_h, CLR_BTN);
   row += g_btn_h + g_gap;

   MakeButton(PREFIX + "CLOSE_BUY", "平多", x + pad, row, g_half_w, g_btn_h, CLR_BTN);
   MakeButton(PREFIX + "CLOSE_SELL", "平空", x + pad + g_half_w + 8, row, g_half_w, g_btn_h, CLR_BTN);
   row += g_btn_h + g_gap;

   MakeButton(PREFIX + "CLOSE_PF", "平盈", x + pad, row, g_half_w, g_btn_h, CLR_BTN);
   MakeButton(PREFIX + "CLOSE_LS", "平亏", x + pad + g_half_w + 8, row, g_half_w, g_btn_h, CLR_BTN);
   row += g_btn_h + g_gap;

   MakeButton(PREFIX + "BE", "一键保本", x + pad, row, 110, g_btn_h, CLR_BTN);
   MakeEdit(PREFIX + "BE_OFF", "0", x + pad + 114, row, 54, g_btn_h);
   row += g_btn_h + g_gap;

   MakeButton(PREFIX + "DEL_PEND", "删除挂单", x + pad, row, g_btn_w, g_btn_h, CLR_BTN);
   row += g_btn_h + g_gap;

   // 挂空=绿, 挂多=红（复刻原面板配色）
   MakeButton(PREFIX + "SELL", "挂空", x + pad, row, g_half_w, g_btn_h, CLR_GREEN, clrWhite);
   MakeButton(PREFIX + "BUY", "挂多", x + pad + g_half_w + 8, row, g_half_w, g_btn_h, CLR_RED, clrWhite);
   row += g_btn_h + g_gap;

   MakeLabel(PREFIX + "SL_L", "止损点数", x + pad + 2, row + 5, clrWhite, 9);
   MakeEdit(PREFIX + "SL", "1000", x + pad + 70, row, g_btn_w - 70, g_btn_h);
   row += g_btn_h + g_gap;

   MakeLabel(PREFIX + "TP_L", "止盈点数", x + pad + 2, row + 5, clrWhite, 9);
   MakeEdit(PREFIX + "TP", "1000", x + pad + 70, row, g_btn_w - 70, g_btn_h);
   row += g_btn_h + g_gap;

   MakeEdit(PREFIX + "LOTS", "0.1", x + pad, row, 60, g_btn_h);
   MakeLabel(PREFIX + "SPREAD", "点差: 0", x + pad + 72, row + 5, clrSilver, 9);
  }

//+------------------------------------------------------------------+
void DestroyPanel()
  {
   ObjectsDeleteAll(0, PREFIX);
  }

//+------------------------------------------------------------------+
void RefreshPanel()
  {
   double profit = FloatingProfit();
   string txt = StringFormat("一键平仓 %.2f", profit);
   ObjectSetString(0, PREFIX + "CLOSE_ALL", OBJPROP_TEXT, txt);
   ObjectSetString(0, PREFIX + "TIME", OBJPROP_TEXT,
                   TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS));

   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   ObjectSetString(0, PREFIX + "SPREAD", OBJPROP_TEXT, StringFormat("点差: %d", spread));

   // 顶栏圆点：绿=可交易，红=未开算法交易/未勾选EA许可
   bool ready = TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)
                && MQLInfoInteger(MQL_TRADE_ALLOWED)
                && AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)
                && AccountInfoInteger(ACCOUNT_TRADE_EXPERT);
   ObjectSetInteger(0, PREFIX + "DOT", OBJPROP_COLOR, ready ? CLR_GREEN : CLR_RED);

   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetAsyncMode(false);
   trade.LogLevel(LOG_LEVEL_ERRORS);
   BuildPanel();
   EventSetTimer(1);
   RefreshPanel();

   bool term_ok = (bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED);
   bool ea_ok   = (bool)MQLInfoInteger(MQL_TRADE_ALLOWED);
   PrintFormat("实盘下单工具看板已加载 | %s | 工具栏算法交易=%s | EA允许交易=%s",
               _Symbol,
               term_ok ? "开" : "关",
               ea_ok ? "开" : "关");
   if(!term_ok || !ea_ok)
      Comment("交易未就绪：",
              !term_ok ? "请按工具栏「算法交易」；" : "",
              !ea_ok ? "请在EA属性勾选「允许算法交易」" : "");
   else
      Comment("");
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   DestroyPanel();
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   RefreshPanel();
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   // 点差/浮盈由 Timer 刷新，避免每 tick 刷对象
  }

//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
  {
   if(id != CHARTEVENT_OBJECT_CLICK)
      return;

   // 松开按钮状态
   ObjectSetInteger(0, sparam, OBJPROP_STATE, false);

   if(sparam == PREFIX + "CLOSE_ALL")
      CloseByFilter(CLOSE_ALL);
   else if(sparam == PREFIX + "CUT50")
      CloseByFilter(CLOSE_PARTIAL, 0.50);
   else if(sparam == PREFIX + "CUT80")
      CloseByFilter(CLOSE_PARTIAL, 0.80);
   else if(sparam == PREFIX + "CLOSE_BUY")
      CloseByFilter(CLOSE_BUY);
   else if(sparam == PREFIX + "CLOSE_SELL")
      CloseByFilter(CLOSE_SELL);
   else if(sparam == PREFIX + "CLOSE_PF")
      CloseByFilter(CLOSE_PROFIT);
   else if(sparam == PREFIX + "CLOSE_LS")
      CloseByFilter(CLOSE_LOSS);
   else if(sparam == PREFIX + "BE")
      BreakEvenAll();
   else if(sparam == PREFIX + "DEL_PEND")
      DeleteAllPendings();
   else if(sparam == PREFIX + "BUY")
      OpenMarket(true);
   else if(sparam == PREFIX + "SELL")
      OpenMarket(false);

   RefreshPanel();
  }

//+------------------------------------------------------------------+
