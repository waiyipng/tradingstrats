import { useEffect, useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent } from 'react'
import { Activity, ArrowDownRight, ArrowUpRight, BadgeDollarSign, Bell, ChevronRight, Clock3, ExternalLink, Radio, X } from 'lucide-react'
import './index.css'

type Signal = { symbol: string; name: string; exchange: string; decision: string; confidence: number | null; sentiment: number | null; urgency: string; articles: number; sources: number; trend: string; price: number | null }
type OrderEvent = { event_id: string; symbol: string; timestamp: string; status: string; broker: string; action: string | null; requested_qty: number; filled_qty: number; price: number | null; reasons: string[]; bracket: { entry_limit: number | null; take_profit: number | null; stop_loss: number | null } }
type Dashboard = { generated_at: string; scheduler: { active: boolean; interval_minutes: number; next_poll: string | null; last_sweep_duration_seconds: number | null; last_sweep_started_at: string | null }; summary: { symbols: number; articles: number; buy_signals: number; sell_signals: number }; symbols: Signal[]; executions: OrderEvent[]; ytd_realized_pnl: number; realized_by_symbol?: RealizedRow[] }
type RealizedRow = { symbol: string; realized_pnl: number; closing_fills: number; last_exit: string | null; reconstructed: boolean }
type AuditArticle = { article_id?: string; title: string; summary: string; url: string; source: string; sentiment?: string; topic?: string; positive_keyword_hits?: number; negative_keyword_hits?: number; positive_keyword_matches?: string[]; negative_keyword_matches?: string[]; raw_sentiment_score?: number; recency_weight?: number; source_article_count?: number; normalized_weight?: number; sentiment_contribution?: number }
type AuditRun = { run_id: string; started_at: string; retained_articles: number }
type AuditDetail = { run_id: string; symbols: Record<string, { signaling?: { article_scores?: AuditArticle[] } }> }
type WheelRun = { generated_at?: string; status?: string; reason?: string; quotes_considered?: number; recommendation?: { action: string; contracts: number; premium_credit: number | null; collateral_required: number; annualized_yield: number | null; reasons: string[] }; execution?: { status: string; reason?: string } }
type WheelPendingApproval = { created_at: string; expires_at: string; recommendation: { symbol: string; action: string; contracts: number; contract: { strike: number; right: string; expiry: string } | null; premium_credit: number | null; collateral_required: number; annualized_yield: number | null; reasons: string[] } }
type Wheel = { connection_mode?: string; scheduler?: { active: boolean; interval_minutes: number; next_run: string | null; last_run_at: string | null }; ytd_realized_pnl: number; latest_runs?: Record<string, WheelRun>; symbols: { symbol: string; market_price: number | null; stock_shares: number; stock_average_cost: number; active_wheel_shares: number; external_shares: number; stock_pool: { shares: number; average_cost: number }; open_options: { side: string; right: string; strike: number; expiry: string; contracts: number; premium: number }[]; tracked_options?: { right: string; strike: number; expiry: string; contracts: number; premium: number }[] }[]; pending_approvals?: Record<string, WheelPendingApproval> }
type GoldLeg = { contract: string; action: string; quantity: number }
type GoldPosition = { id: string; type: string; action: string; opened_at: string; legs: GoldLeg[]; entry_net_edge: number; status: string }
type GoldQuote = { symbol: string; bid: number | null; ask: number | null; expiry?: string; days_to_expiry?: number }
type GoldLadder = { days_to_expiry: number; years_to_expiry: number; financing_rate_annual: number; storage_rate_annual: number; convenience_yield_annual: number; carry_rate_annual: number; spot_price: number; carry_cost_amount: number; theoretical_price: number; market_price: number; raw_mispricing: number }
type GoldRecommendation = { action: string; net_edge_after_costs: number | null; reasons: string[]; entry_basis?: number | null; theoretical_futures_price?: number | null; market_spread?: number | null; theoretical_spread?: number | null; mispricing?: number | null; ladder?: GoldLadder | null; near_ladder?: GoldLadder | null; far_ladder?: GoldLadder | null; round_trip_cost?: number | null; min_net_edge_threshold?: number | null; is_arbitrage_opportunity?: boolean; verdict?: string | null }
type GoldRun = { generated_at?: string; status?: string; reason?: string; cash_and_carry?: { recommendation: GoldRecommendation; execution: { status: string; reason?: string } }; calendar_spread?: { recommendation: GoldRecommendation; execution: { status: string; reason?: string } } }
type GoldPendingApproval = { kind: 'entry_cash_and_carry' | 'entry_calendar_spread' | 'exit'; created_at: string; expires_at: string; payload: { recommendation?: GoldRecommendation; position_id?: string; reason?: string } }
type Gold = { connection_mode?: string; realized_pnl: number; ytd_realized_pnl?: number; spot?: GoldQuote | null; near_future?: GoldQuote | null; far_future?: GoldQuote | null; open_positions: GoldPosition[]; latest_run?: GoldRun | null; scheduler?: { active: boolean; interval_minutes: number; next_run: string | null; last_run_at: string | null }; pending_approval?: GoldPendingApproval | null }
type SpreadLeg = { strike: number; bid: number | null; ask: number | null; expiry: string }
type SpreadPayoffPoint = { price: number; label: string; profit_loss: number }
type SpreadExitPlan = { stop_loss_debit_value: number; stop_loss_pct_of_debit: number; exit_by_date: string; notes: string[] }
type SpreadRecommendation = { action: string; symbol: string; target_price: number; target_date: string; expiry: string | null; long_leg: SpreadLeg | null; short_leg: SpreadLeg | null; contracts: number; net_debit: number | null; max_profit: number | null; max_loss: number | null; breakeven: number | null; return_on_debit_pct: number | null; payoff_ladder: SpreadPayoffPoint[]; exit_plan: SpreadExitPlan | null; reasons: string[] }
type AnalystPrediction = { symbol: string; earnings_date: string; predicted_price: number; price_range_low: number; price_range_high: number; confidence: string; predicted_eps: number | null; implied_surprise_pct: number | null; consensus_summary: string; reasoning: string[]; input_confidence_pct: number }
type TradingAgentReport = { reasoning: string[]; alternatives_considered: string[]; primary_risk: string }
type NasdaqEpsForecast = { fiscal_quarter_end: string; consensus_eps: number | null; eps_low: number | null; eps_high: number | null; num_estimates: number | null; revisions_up: number | null; revisions_down: number | null }
type ConsensusSnapshot = { consensus_eps: number | null; eps_low: number | null; eps_high: number | null; analyst_target_mean: number | null; analyst_target_median: number | null; nasdaq_forecast: NasdaqEpsForecast | null }
type BullSpreadRun = { generated_at?: string; mode?: string; status?: string; reason?: string; spot_price?: number; bull_call_spread?: SpreadRecommendation; analyst_prediction?: AnalystPrediction; trading_agent?: TradingAgentReport; consensus?: ConsensusSnapshot }
type PnlPoint = { timestamp: string; current_value: number; unrealized_pnl: number; exit_signal: string | null }
type BullSpreadPosition = { id: string; symbol: string; opened_at: string; legs: { strike: number; action: string; expiry: string }[]; entry_net_debit: number; contracts: number; status: string; pnl_history?: PnlPoint[] }
type BullSpread = { status?: string; reason?: string; latest_run_at?: string | null; latest_recommendation?: BullSpreadRun | null; latest_execution?: { status: string; reason: string; order_id?: number | null; limit_price?: number | null } | null; open_positions: BullSpreadPosition[]; scheduler?: { active: boolean; interval_minutes: number; next_run: string | null; last_run_at: string | null }; connection_mode?: string }
type BtcVote = { name: string; long: boolean; detail: string }
type BtcSignal = { bar_date: string; close: number; votes: BtcVote[]; score: number; realized_vol_annual: number; vol_scalar: number; target_exposure: number; return_30d_pct: number; drawdown_from_high_pct: number; atr: number; reentry_breakout_level: number }
type BtcRecommendation = { action: string; signal_target_exposure: number; held_exposure_before: number; new_held_exposure: number; sleeve_usd: number; current_qty: number; target_qty: number; order_qty: number; limit_price: number | null; order_notional: number; reasons: string[]; peak_close: number; stop_price: number | null; stop_triggered: boolean; reentry_locked: boolean; entry_price: number; profit_taken: boolean; risk_at_stop_usd: number; risk_at_stop_pct_of_net_liq: number; stop_price_if_filled: number | null }
type BtcBar = { date: string; close: number; sma50: number | null; sma200: number | null; donchian55_upper: number | null; donchian20_lower: number | null; atr14: number | null }
type BtcRun = { generated_at?: string; mode?: string; status?: string; reason?: string; signal?: BtcSignal; data?: { last_bar: string; bar_age_days: number; stale: boolean }; quote?: { bid: number | null; ask: number | null; last: number | null }; recommendation?: BtcRecommendation; execution?: { status: string; reason?: string; filled_qty?: number; avg_fill_price?: number | null } }
type BtcPerf = { cagr_pct: number; sharpe: number; max_drawdown_pct: number; calmar: number; avg_exposure_pct: number; turnover_per_year: number }
type BtcBacktestResult = { in_sample: BtcPerf; out_of_sample: BtcPerf; full: BtcPerf; yearly_returns_pct: Record<string, number> }
type BtcBacktest = { generated_at: string; data: { first_bar: string; last_bar: string; bars: number }; assumptions: { cost_per_side: number; in_sample: string; out_of_sample: string }; results: Record<string, BtcBacktestResult> }
type BtcFill = { timestamp: string; action: string; qty: number; price: number; order_id: number | null; realized_pnl: number }
type BtcPendingApproval = { created_at: string; expires_at: string; recommendation: BtcRecommendation }
type BtcTrend = { status?: string; reason?: string; latest_run: BtcRun | null; position: { btc_qty: number; avg_cost: number; held_exposure: number; target_qty: number; target_set_at: string | null; realized_pnl: number; peak_close: number; stop_locked: boolean; entry_price: number; profit_taken: boolean } | null; recent_fills: BtcFill[]; ytd_realized_pnl: number; backtest: BtcBacktest | null; scheduler?: { active: boolean; interval_minutes: number; next_run: string | null; last_run_at: string | null; stale?: boolean }; pending_approval: BtcPendingApproval | null; connection_mode?: string }

const money = (value: number | null | undefined) => value == null ? '---' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value)
const money4 = (value: number | null | undefined) => value == null ? '---' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(value)
const pct = (value: number | null | undefined, digits = 3) => value == null ? '---' : `${(value * 100).toFixed(digits)}%`
const clock = (value: string | null) => value ? new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(new Date(value.includes('T') ? value : `${value.replace(' ', 'T')}-04:00`)) : 'Waiting'
const dateTime = (value: string | null) => value ? new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(value)) : 'No data'
const duration = (seconds: number | null) => seconds == null ? 'Calculating' : `${Math.floor(seconds / 60)}m ${seconds % 60}s`

function ScoreMath({ article }: { article: AuditArticle }) {
  const positive = article.positive_keyword_hits ?? 0
  const negative = article.negative_keyword_hits ?? 0
  return <details className="score-math"><summary>Explain this score</summary><div><p><b>Raw sentiment:</b> ({positive} positive - {negative} negative) / ({positive} + {negative} + 1) = <strong>{article.raw_sentiment_score?.toFixed(4) ?? '---'}</strong></p><p><b>Normalized weight:</b> source weight x recency / source articles = <strong>{article.normalized_weight?.toFixed(4) ?? '---'}</strong>. Source articles: {article.source_article_count ?? '---'}; recency: {article.recency_weight?.toFixed(4) ?? '---'}.</p><p><b>Contribution:</b> raw sentiment x normalized weight = <strong>{article.sentiment_contribution?.toFixed(4) ?? '---'}</strong>.</p><div className="keyword-matches"><span>Positive matches: {(article.positive_keyword_matches ?? []).join(', ') || 'none'}</span><span>Negative matches: {(article.negative_keyword_matches ?? []).join(', ') || 'none'}</span></div></div></details>
}

type HeroProps = { active?: boolean; title: string; subhead: string; ytdPnl?: number | null; nextLabel: string; nextValue: string | null; lastValue: string; lastNote: string }

// Shared header so every strategy tab shows state, YTD P&L, and scheduler timing in the same place.
function StrategyHero({ active, title, subhead, ytdPnl, nextLabel, nextValue, lastValue, lastNote }: HeroProps) {
  const pnl = ytdPnl ?? 0
  return <section className="hero-row"><div><p className="eyebrow">OPERATIONS CONSOLE <span className={active ? 'live-state' : 'idle-state'}>{active ? 'LIVE' : 'IDLE'}</span></p><h1>{title}</h1><p className="subhead">{subhead}</p></div><div className="hero-row-right"><div className="wheel-ytd"><BadgeDollarSign size={18} /><span>STRATEGY YTD REALIZED P&amp;L</span><strong className={pnl >= 0 ? 'positive' : 'negative'}>{money(pnl)}</strong></div><div className="sweep-status"><div className="next-run"><Radio size={17} /><div><span>{nextLabel}</span><strong>{clock(nextValue)}</strong></div></div><div className="sweep-meta"><span>LAST RUN</span><strong>{lastValue}</strong><small>{lastNote}</small></div></div></div></section>
}

function LadderBreakdown({ ladder, label }: { ladder?: GoldLadder | null; label: string }) {
  if (!ladder) return <div className="ladder-block"><p className="ladder-label">{label}</p><p>No live quote data in the latest run.</p></div>
  return <div className="ladder-block"><p className="ladder-label">{label}</p><p><b>Carry rate:</b> financing {pct(ladder.financing_rate_annual)} + storage {pct(ladder.storage_rate_annual)} - convenience {pct(ladder.convenience_yield_annual)} = <strong>{pct(ladder.carry_rate_annual)}/yr</strong></p><p><b>Time to expiry:</b> {ladder.days_to_expiry} days / 365 = <strong>{ladder.years_to_expiry.toFixed(4)} yr</strong></p><p><b>Theoretical price:</b> spot {money(ladder.spot_price)} &times; (1 + {pct(ladder.carry_rate_annual)} &times; {ladder.years_to_expiry.toFixed(4)}) = <strong>{money(ladder.theoretical_price)}</strong> (cost of carry {money4(ladder.carry_cost_amount)})</p><p><b>Market price:</b> <strong>{money(ladder.market_price)}</strong> &middot; raw mispricing (market − theoretical) = <strong>{money4(ladder.raw_mispricing)}</strong></p></div>
}

// Renders the vertical-spread payoff diagram (flat loss, linear ramp, flat profit)
// as an inline SVG so the dashboard needs no charting dependency. Reference
// price labels live in a legend row above the chart (not on the plot itself)
// so they never overlap each other when strikes sit close together; hovering
// the plot shows a crosshair and the projected P&L at that price.
function PayoffChart({ rec, spot }: { rec: SpreadRecommendation; spot?: number | null }) {
  const [hoverPrice, setHoverPrice] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement | null>(null)

  if (!rec.long_leg || !rec.short_leg || rec.net_debit == null || !rec.contracts) {
    return <p>No payoff data available in the latest run.</p>
  }
  const long = rec.long_leg.strike
  const short = rec.short_leg.strike
  const debit = rec.net_debit
  const contracts = rec.contracts
  const breakeven = rec.breakeven ?? long + debit
  const width = short - long
  const pad = Math.max(width * 0.6, 2)
  const priceMin = Math.min(long - pad, spot ?? long - pad)
  const priceMax = Math.max(short + pad, spot ?? short + pad)
  const payoffAt = (price: number) => (Math.max(0, Math.min(price, short) - long) - debit) * 100 * contracts
  const steps = 48
  const points = Array.from({ length: steps + 1 }, (_, i) => {
    const price = priceMin + ((priceMax - priceMin) * i) / steps
    return { price, pl: payoffAt(price) }
  })
  const maxLoss = payoffAt(long)
  const maxProfit = payoffAt(short)

  const svgW = 640, svgH = 300, marginL = 70, marginR = 20, marginT = 16, marginB = 36
  const plotW = svgW - marginL - marginR, plotH = svgH - marginT - marginB
  const yMin = Math.min(maxLoss, 0) * 1.15
  const yMax = Math.max(maxProfit, 0) * 1.15
  const xScale = (price: number) => marginL + ((price - priceMin) / (priceMax - priceMin)) * plotW
  const yScale = (pl: number) => marginT + (1 - (pl - yMin) / (yMax - yMin)) * plotH
  const priceFromX = (x: number) => priceMin + ((x - marginL) / plotW) * (priceMax - priceMin)
  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xScale(p.price).toFixed(2)} ${yScale(p.pl).toFixed(2)}`).join(' ')
  const areaD = `${pathD} L ${xScale(priceMax).toFixed(2)} ${yScale(0).toFixed(2)} L ${xScale(priceMin).toFixed(2)} ${yScale(0).toFixed(2)} Z`
  const refLines: { price: number; label: string; swatch: string }[] = [
    { price: long, label: `Long ${long}`, swatch: 'long' },
    { price: breakeven, label: `Breakeven ${breakeven.toFixed(2)}`, swatch: 'be' },
    { price: short, label: `Short ${short}`, swatch: 'short' },
  ]
  if (spot != null) refLines.unshift({ price: spot, label: `Spot ${spot.toFixed(2)}`, swatch: 'spot' })
  const xTicks = Array.from({ length: 7 }, (_, i) => priceMin + ((priceMax - priceMin) * i) / 6)

  const handleMove = (event: ReactMouseEvent<SVGSVGElement>) => {
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    const x = ((event.clientX - rect.left) / rect.width) * svgW
    const price = Math.min(priceMax, Math.max(priceMin, priceFromX(x)))
    setHoverPrice(price)
  }

  const hoverPl = hoverPrice != null ? payoffAt(hoverPrice) : null

  return <div className="payoff-chart">
    <div className="payoff-legend">{refLines.map((line, index) => <span key={index} className={`payoff-legend-item swatch-${line.swatch}`}>{line.label}</span>)}</div>
    <svg ref={svgRef} viewBox={`0 0 ${svgW} ${svgH}`} role="img" aria-label="Bull call spread payoff diagram" onMouseMove={handleMove} onMouseLeave={() => setHoverPrice(null)}>
      <line x1={marginL} y1={yScale(0)} x2={svgW - marginR} y2={yScale(0)} className="payoff-zero-line" />
      {xTicks.map((price, index) => <g key={index}><line x1={xScale(price)} y1={marginT} x2={xScale(price)} y2={svgH - marginB} className="payoff-grid-line" /><text x={xScale(price)} y={svgH - marginB + 16} textAnchor="middle" className="payoff-axis-label">{money(price)}</text></g>)}
      {[yMax, yMax / 2, 0, yMin / 2, yMin].map((value, index) => <text key={index} x={marginL - 10} y={yScale(value) + 3} textAnchor="end" className="payoff-axis-label">{money(value)}</text>)}
      {refLines.map((line, index) => <line key={index} x1={xScale(line.price)} y1={marginT} x2={xScale(line.price)} y2={svgH - marginB} className={`payoff-ref-line swatch-${line.swatch}`} />)}
      <path d={areaD} className="payoff-area" />
      <path d={pathD} className="payoff-line" />
      <text x={marginL + 6} y={yScale(maxLoss) - 8} className="payoff-annotation negative">Max loss: {money(maxLoss)}</text>
      <text x={svgW - marginR - 6} y={yScale(maxProfit) + 16} textAnchor="end" className="payoff-annotation positive">Max profit: {money(maxProfit)}</text>
      {hoverPrice != null && hoverPl != null && <g className="payoff-hover">
        <line x1={xScale(hoverPrice)} y1={marginT} x2={xScale(hoverPrice)} y2={svgH - marginB} className="payoff-hover-line" />
        <circle cx={xScale(hoverPrice)} cy={yScale(hoverPl)} r={4} className="payoff-hover-dot" />
        {(() => {
          const boxW = 128, boxH = 40
          const nearRightEdge = xScale(hoverPrice) + 10 + boxW > svgW - marginR
          const boxX = nearRightEdge ? xScale(hoverPrice) - 10 - boxW : xScale(hoverPrice) + 10
          const boxY = Math.min(Math.max(yScale(hoverPl) - boxH / 2, marginT), svgH - marginB - boxH)
          return <g transform={`translate(${boxX}, ${boxY})`}>
            <rect width={boxW} height={boxH} rx={3} className="payoff-tooltip-box" />
            <text x={10} y={16} className="payoff-tooltip-text">Price {money(hoverPrice)}</text>
            <text x={10} y={31} className={`payoff-tooltip-text ${hoverPl >= 0 ? 'positive' : 'negative'}`}>P&amp;L {money(hoverPl)}</text>
          </g>
        })()}
      </g>}
    </svg>
  </div>
}

// Line chart of the actual unrealized P&L history recorded by monitor.py for
// an open position (as opposed to PayoffChart, which is a projection).
function UnrealizedPnlChart({ history }: { history: PnlPoint[] }) {
  if (!history.length) return <p>No unrealized P&amp;L history yet &mdash; the next scheduled monitor cycle will record the first mark.</p>
  const svgW = 640, svgH = 220, marginL = 70, marginR = 20, marginT = 16, marginB = 30
  const plotW = svgW - marginL - marginR, plotH = svgH - marginT - marginB
  const values = history.map((point) => point.unrealized_pnl)
  const yMin = Math.min(0, ...values) * 1.15
  const yMax = Math.max(0, ...values) * 1.15 || 1
  const xScale = (index: number) => marginL + (history.length === 1 ? plotW / 2 : (plotW * index) / (history.length - 1))
  const yScale = (pnl: number) => marginT + (1 - (pnl - yMin) / (yMax - yMin)) * plotH
  const pathD = history.map((point, index) => `${index === 0 ? 'M' : 'L'} ${xScale(index).toFixed(2)} ${yScale(point.unrealized_pnl).toFixed(2)}`).join(' ')
  const latest = history[history.length - 1]
  const tickIndexes = history.length <= 6 ? history.map((_, index) => index) : [0, Math.floor((history.length - 1) / 2), history.length - 1]

  return <div className="payoff-chart">
    <svg viewBox={`0 0 ${svgW} ${svgH}`} role="img" aria-label="Unrealized P&L history">
      <line x1={marginL} y1={yScale(0)} x2={svgW - marginR} y2={yScale(0)} className="payoff-zero-line" />
      {[yMax, yMax / 2, 0, yMin / 2, yMin].map((value, index) => <text key={index} x={marginL - 10} y={yScale(value) + 3} textAnchor="end" className="payoff-axis-label">{money(value)}</text>)}
      {tickIndexes.map((index) => <text key={index} x={xScale(index)} y={svgH - marginB + 16} textAnchor="middle" className="payoff-axis-label">{dateTime(history[index].timestamp)}</text>)}
      <path d={pathD} className={latest.unrealized_pnl >= 0 ? 'payoff-line positive-line' : 'payoff-line negative-line'} />
      {history.map((point, index) => <circle key={index} cx={xScale(index)} cy={yScale(point.unrealized_pnl)} r={point.exit_signal ? 5 : 3} className={point.exit_signal ? 'payoff-hover-dot exit-flag' : 'payoff-hover-dot'} />)}
      <text x={svgW - marginR - 6} y={marginT + 10} textAnchor="end" className={`payoff-annotation ${latest.unrealized_pnl >= 0 ? 'positive' : 'negative'}`}>Latest: {money(latest.unrealized_pnl)}</text>
    </svg>
    {latest.exit_signal && <p className="exit-signal-note">Suggested exit condition reached: {latest.exit_signal}</p>}
  </div>
}

function ArbitrageVerdict({ rec }: { rec?: GoldRecommendation | null }) {
  if (!rec) return <p>No recommendation available from the latest run.</p>
  return <><p><b>Round-trip cost (other costs):</b> <strong>{money4(rec.round_trip_cost)}</strong></p><p><b>Net edge after costs:</b> <strong>{money4(rec.net_edge_after_costs)}</strong></p><p><b>Minimum required edge:</b> <strong>{money4(rec.min_net_edge_threshold)}</strong></p><span className={`arb-badge ${rec.is_arbitrage_opportunity ? 'positive' : 'negative'}`}>{rec.is_arbitrage_opportunity ? 'ARBITRAGE OPPORTUNITY' : 'NO ARBITRAGE OPPORTUNITY'}</span><p>{rec.verdict ?? rec.reasons?.[0] ?? '---'}</p></>
}

const BTC_VARIANTS: [string, string][] = [['strategy', 'Strategy (signals + 4x ATR stop + profit trim)'], ['no_profit_taking', 'Without the profit trim'], ['signal_exits_only', 'Signal exits only, no stop or trim'], ['buy_and_hold', 'Buy and hold']]

function BtcBacktestTable({ backtest }: { backtest: BtcBacktest }) {
  return <div className="btc-table">
    <div className="btc-bt-head"><span>VARIANT / PERIOD</span><span>CAGR</span><span>SHARPE</span><span>MAX DD</span><span>EXPOSURE</span><span>TURNOVER/YR</span></div>
    {BTC_VARIANTS.map(([key, label]) => backtest.results[key] && (['out_of_sample', 'in_sample', 'full'] as const).map((period) => {
      const perf = backtest.results[key][period]
      return <div className={period === 'out_of_sample' ? 'btc-bt-row first' : 'btc-bt-row'} key={`${key}-${period}`}><span>{period === 'out_of_sample' && <strong>{label}</strong>}<em>{period === 'out_of_sample' ? `out of sample (${backtest.assumptions.out_of_sample})` : period === 'in_sample' ? `in sample (${backtest.assumptions.in_sample})` : 'full history'}</em></span><span className={perf.cagr_pct >= 0 ? 'positive' : 'negative'}>{perf.cagr_pct.toFixed(1)}%</span><span>{perf.sharpe.toFixed(2)}</span><span className="negative">{perf.max_drawdown_pct.toFixed(1)}%</span><span>{perf.avg_exposure_pct.toFixed(0)}%</span><span>{perf.turnover_per_year.toFixed(1)}</span></div>
    }))}
  </div>
}

// Paired bars per calendar year: strategy vs buy-and-hold, on a symmetric log-ish (signed sqrt) scale
// so 2017's +1,369% does not flatten every other year.
function BtcYearlyChart({ backtest }: { backtest: BtcBacktest }) {
  const strategy = backtest.results.strategy?.yearly_returns_pct ?? {}
  const hold = backtest.results.buy_and_hold?.yearly_returns_pct ?? {}
  const years = Object.keys(strategy)
  if (!years.length) return null
  const scale = (value: number) => Math.sign(value) * Math.sqrt(Math.abs(value))
  const maxAbs = Math.max(...years.flatMap((year) => [Math.abs(scale(strategy[year])), Math.abs(scale(hold[year] ?? 0))]), 1)
  const svgW = 1100, svgH = 240, marginL = 16, marginR = 16, marginT = 16, marginB = 26
  const plotH = svgH - marginT - marginB, slot = (svgW - marginL - marginR) / years.length, barW = Math.min(16, slot / 2 - 3)
  const zeroY = marginT + plotH / 2
  const y = (value: number) => zeroY - (scale(value) / maxAbs) * (plotH / 2)
  const bar = (value: number, x: number, cls: string, key: string) => <rect key={key} x={x} width={barW} y={Math.min(y(value), zeroY)} height={Math.max(1, Math.abs(y(value) - zeroY))} rx={2} className={cls}><title>{`${key.split('-')[0]}: ${value.toFixed(0)}%`}</title></rect>
  return <div className="payoff-chart">
    <div className="btc-legend"><span className="swatch strategy" /> Strategy <span className="swatch hold" /> Buy and hold <em>signed square-root scale; hover a bar for the value</em></div>
    <svg viewBox={`0 0 ${svgW} ${svgH}`} role="img" aria-label="Yearly returns, strategy vs buy and hold">
      <line x1={marginL} x2={svgW - marginR} y1={zeroY} y2={zeroY} className="payoff-zero-line" />
      {years.map((year, index) => {
        const center = marginL + slot * index + slot / 2
        return <g key={year}>{bar(strategy[year], center - barW - 1, 'btc-bar strategy', `${year}-s`)}{bar(hold[year] ?? 0, center + 1, 'btc-bar hold', `${year}-h`)}<text x={center} y={svgH - 8} textAnchor="middle" className="payoff-axis-label">{year.slice(2)}</text></g>
      })}
    </svg>
  </div>
}

// Close price with SMA50/SMA200 overlays, the 55/20-day Donchian band, and the
// live trailing-stop level (peak close since entry minus 4x ATR14), so the chart
// shows the same inputs the ensemble signal votes on.
function BtcPriceChart({ bars, stopPrice, suggestedStopPrice }: { bars: BtcBar[]; stopPrice: number | null | undefined; suggestedStopPrice: number | null | undefined }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  if (!bars.length) return <p>No price history available yet.</p>
  const svgW = 1100, svgH = 300, marginL = 70, marginR = 16, marginT = 16, marginB = 26
  const plotW = svgW - marginL - marginR, plotH = svgH - marginT - marginB
  const values = bars.flatMap((bar) => [bar.close, bar.sma50, bar.sma200, bar.donchian55_upper, bar.donchian20_lower].filter((v): v is number => v != null))
  if (stopPrice != null) values.push(stopPrice)
  if (suggestedStopPrice != null) values.push(suggestedStopPrice)
  const yMin = Math.min(...values) * 0.97
  const yMax = Math.max(...values) * 1.03
  const xScale = (index: number) => marginL + (bars.length === 1 ? plotW / 2 : (plotW * index) / (bars.length - 1))
  const yScale = (value: number) => marginT + (1 - (value - yMin) / (yMax - yMin)) * plotH
  const pathFor = (key: 'close' | 'sma50' | 'sma200') => {
    let d = '', started = false
    bars.forEach((bar, index) => {
      const value = bar[key]
      if (value == null) { started = false; return }
      d += `${started ? 'L' : 'M'} ${xScale(index).toFixed(2)} ${yScale(value).toFixed(2)} `
      started = true
    })
    return d.trim()
  }
  const bandPath = (() => {
    const upper: [number, number][] = [], lower: [number, number][] = []
    bars.forEach((bar, index) => {
      if (bar.donchian55_upper == null || bar.donchian20_lower == null) return
      upper.push([xScale(index), yScale(bar.donchian55_upper)])
      lower.push([xScale(index), yScale(bar.donchian20_lower)])
    })
    if (!upper.length) return ''
    return `M${upper.map((p) => p.join(',')).join(' L')} L${lower.reverse().map((p) => p.join(',')).join(' L')} Z`
  })()
  const labelEvery = Math.ceil(bars.length / 7)
  const hover = hoverIndex != null ? bars[hoverIndex] : null

  const handleMove = (event: ReactMouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const x = ((event.clientX - rect.left) / rect.width) * svgW
    const index = Math.round(((x - marginL) / plotW) * (bars.length - 1))
    setHoverIndex(Math.max(0, Math.min(bars.length - 1, index)))
  }

  return <div className="payoff-chart">
    <div className="btc-legend">
      <span className="swatch strategy" /> BTC close <span className="swatch spot" /> SMA 50 <span className="swatch hold" /> SMA 200
      <em>shaded band: 55-day high / 20-day low (Donchian)</em>
      {stopPrice != null && <em className="negative">--- active trailing stop {money(stopPrice)}</em>}
      {suggestedStopPrice != null && <em className="negative">&bull; suggested stop if filled {money(suggestedStopPrice)}</em>}
    </div>
    <svg viewBox={`0 0 ${svgW} ${svgH}`} role="img" aria-label="BTC close price with moving averages, Donchian band and trailing stop" onMouseMove={handleMove} onMouseLeave={() => setHoverIndex(null)}>
      {[yMax, yMax * 0.75 + yMin * 0.25, (yMax + yMin) / 2, yMax * 0.25 + yMin * 0.75, yMin].map((value, index) => <g key={index}><line x1={marginL} x2={svgW - marginR} y1={yScale(value)} y2={yScale(value)} className="payoff-grid-line" /><text x={marginL - 10} y={yScale(value) + 3} textAnchor="end" className="payoff-axis-label">{money(value)}</text></g>)}
      {bars.map((bar, index) => (index % labelEvery === 0) && <text key={bar.date} x={xScale(index)} y={svgH - 8} textAnchor="middle" className="payoff-axis-label">{bar.date.slice(5)}</text>)}
      <path d={bandPath} className="btc-band" />
      <path d={pathFor('sma200')} className="payoff-line" style={{ stroke: '#d99a3a' }} />
      <path d={pathFor('sma50')} className="payoff-line" style={{ stroke: '#276b92' }} />
      <path d={pathFor('close')} className="payoff-line positive-line" />
      {stopPrice != null && <>
        <line x1={marginL} x2={svgW - marginR} y1={yScale(stopPrice)} y2={yScale(stopPrice)} className="payoff-ref-line swatch-short" />
      </>}
      {suggestedStopPrice != null && (() => {
        const px = xScale(bars.length - 1), py = yScale(suggestedStopPrice)
        const labelW = 150
        return <g>
          <circle cx={px} cy={py} r={5} className="btc-stop-suggestion-dot" />
          <rect x={px - labelW - 10} y={py - 10} width={labelW} height={20} rx={3} className="payoff-tooltip-box" />
          <text x={px - labelW} y={py + 4} className="payoff-tooltip-text negative">stop if filled {money(suggestedStopPrice)}</text>
        </g>
      })()}
      {hover && <g className="payoff-hover">
        <line x1={xScale(hoverIndex!)} y1={marginT} x2={xScale(hoverIndex!)} y2={svgH - marginB} className="payoff-hover-line" />
        <circle cx={xScale(hoverIndex!)} cy={yScale(hover.close)} r={4} className="payoff-hover-dot" />
        {(() => {
          const boxW = 150, boxH = 54
          const px = xScale(hoverIndex!)
          const nearRightEdge = px + 10 + boxW > svgW - marginR
          const boxX = nearRightEdge ? px - 10 - boxW : px + 10
          const boxY = Math.min(Math.max(yScale(hover.close) - boxH / 2, marginT), svgH - marginB - boxH)
          return <g transform={`translate(${boxX}, ${boxY})`}>
            <rect width={boxW} height={boxH} rx={3} className="payoff-tooltip-box" />
            <text x={10} y={16} className="payoff-tooltip-text">{hover.date}</text>
            <text x={10} y={31} className="payoff-tooltip-text">close {money(hover.close)}</text>
            <text x={10} y={46} className="payoff-tooltip-text">{hover.sma50 != null ? `SMA50 ${money(hover.sma50)}` : ''}</text>
          </g>
        })()}
      </g>}
    </svg>
  </div>
}

export default function App() {
  const [view, setView] = useState<'EQUITY' | 'WHEEL' | 'GOLD' | 'BULLSPREAD' | 'BTC'>('EQUITY')
  const [data, setData] = useState<Dashboard | null>(null)
  const [wheel, setWheel] = useState<Wheel | null>(null)
  const [gold, setGold] = useState<Gold | null>(null)
  const [bullSpread, setBullSpread] = useState<BullSpread | null>(null)
  const [btc, setBtc] = useState<BtcTrend | null>(null)
  const [btcBars, setBtcBars] = useState<BtcBar[]>([])
  const [btcApprovalBusy, setBtcApprovalBusy] = useState(false)
  const [btcApprovalResult, setBtcApprovalResult] = useState<{ status: string; reason?: string } | null>(null)
  const [wheelApprovalBusy, setWheelApprovalBusy] = useState<string | null>(null)
  const [wheelApprovalResult, setWheelApprovalResult] = useState<Record<string, { status: string; reason?: string }>>({})
  const [goldApprovalBusy, setGoldApprovalBusy] = useState(false)
  const [goldApprovalResult, setGoldApprovalResult] = useState<{ status: string; reason?: string } | null>(null)
  const [status, setStatus] = useState('ALL')
  const [selectedOrder, setSelectedOrder] = useState<OrderEvent | null>(null)
  const [selectedSignal, setSelectedSignal] = useState<string | null>(null)
  const [runs, setRuns] = useState<AuditRun[]>([])
  const [audit, setAudit] = useState<AuditDetail | null>(null)
  const [symbol, setSymbol] = useState('')
  const [shown, setShown] = useState(10)
  const [eventPage, setEventPage] = useState(0)
  const [selectedWheel, setSelectedWheel] = useState<Wheel['symbols'][number] | null>(null)
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768)

  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth <= 768)
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  useEffect(() => {
    const load = async () => { const response = await fetch('/api/dashboard'); if (response.ok) setData(await response.json()) }
    void load(); const interval = window.setInterval(() => void load(), 15_000); return () => window.clearInterval(interval)
  }, [])
  useEffect(() => {
    const load = async () => { const response = await fetch('/api/wheel-status'); if (response.ok) setWheel(await response.json()) }
    void load(); const interval = window.setInterval(() => void load(), 30_000); return () => window.clearInterval(interval)
  }, [])
  useEffect(() => {
    const load = async () => { const response = await fetch('/api/gold-status'); if (response.ok) setGold(await response.json()) }
    void load(); const interval = window.setInterval(() => void load(), 30_000); return () => window.clearInterval(interval)
  }, [])
  useEffect(() => {
    const load = async () => { const response = await fetch('/api/bullcallspread-status'); if (response.ok) setBullSpread(await response.json()) }
    void load(); const interval = window.setInterval(() => void load(), 30_000); return () => window.clearInterval(interval)
  }, [])
  useEffect(() => {
    const load = async () => { const response = await fetch('/api/btctrend-status'); if (response.ok) setBtc(await response.json()) }
    void load(); const interval = window.setInterval(() => void load(), 30_000); return () => window.clearInterval(interval)
  }, [])
  useEffect(() => {
    const load = async () => { const response = await fetch('/api/btctrend-bars'); if (response.ok) setBtcBars((await response.json()).bars ?? []) }
    void load(); const interval = window.setInterval(() => void load(), 300_000); return () => window.clearInterval(interval)
  }, [])
  useEffect(() => {
    const loadRuns = async () => { const response = await fetch('/api/audit-runs'); if (!response.ok) return; const value: AuditRun[] = await response.json(); setRuns(value); if (value[0]) await selectRun(value[0].run_id) }
    void loadRuns()
  }, [])
  useEffect(() => setShown(10), [symbol, audit?.run_id])

  const selectRun = async (runId: string) => { const response = await fetch(`/api/audit-runs/${runId}`); if (!response.ok) return; const detail: AuditDetail = await response.json(); setAudit(detail); setSymbol(Object.keys(detail.symbols)[0] ?? '') }
  const statuses = ['ALL', ...Array.from(new Set(data?.executions.map((event) => event.status) ?? [])).sort()]
  const events = data?.executions.filter((event) => status === 'ALL' || event.status === status) ?? []
  const visibleEvents = events.slice(eventPage * 10, eventPage * 10 + 10)
  const eventPages = Math.max(1, Math.ceil(events.length / 10))
  const articles = [...(audit?.symbols[symbol]?.signaling?.article_scores ?? [])].sort((a, b) => Math.abs(b.sentiment_contribution ?? 0) - Math.abs(a.sentiment_contribution ?? 0))
  const signalArticles = [...(audit?.symbols[selectedSignal ?? '']?.signaling?.article_scores ?? [])].sort((a, b) => Math.abs(b.sentiment_contribution ?? 0) - Math.abs(a.sentiment_contribution ?? 0))
  const goldCarryRec = gold?.latest_run?.cash_and_carry?.recommendation
  const goldCalendarRec = gold?.latest_run?.calendar_spread?.recommendation
  const bullSpreadRec = bullSpread?.latest_recommendation?.bull_call_spread
  const analystPrediction = bullSpread?.latest_recommendation?.analyst_prediction
  const consensusSnapshot = bullSpread?.latest_recommendation?.consensus
  const tradingAgent = bullSpread?.latest_recommendation?.trading_agent
  const btcRun = btc?.latest_run
  const btcSignal = btcRun?.signal
  const btcRec = btcRun?.recommendation
  const btcPosition = btc?.position
  const btcMark = btcRun?.quote?.bid && btcRun?.quote?.ask ? (btcRun.quote.bid + btcRun.quote.ask) / 2 : btcSignal?.close ?? null
  const btcUnrealized = btcPosition && btcPosition.btc_qty > 0 && btcMark ? (btcMark - btcPosition.avg_cost) * btcPosition.btc_qty : null
  const btcPending = btc?.pending_approval ?? null
  const decideWheelPending = async (symbol: string, action: 'approve' | 'reject') => {
    setWheelApprovalBusy(symbol)
    try {
      const response = await fetch(`/api/wheel-${action}/${symbol}`, { method: 'POST' })
      const result = response.ok ? await response.json() : { status: 'ERROR', reason: 'request failed' }
      setWheelApprovalResult((previous) => ({ ...previous, [symbol]: result }))
    } catch {
      setWheelApprovalResult((previous) => ({ ...previous, [symbol]: { status: 'ERROR', reason: 'request failed' } }))
    } finally {
      setWheelApprovalBusy(null)
      const response = await fetch('/api/wheel-status'); if (response.ok) setWheel(await response.json())
    }
  }
  const decideGoldPending = async (action: 'approve' | 'reject') => {
    setGoldApprovalBusy(true)
    try {
      const response = await fetch(`/api/goldtrading-${action}`, { method: 'POST' })
      setGoldApprovalResult(response.ok ? await response.json() : { status: 'ERROR', reason: 'request failed' })
    } catch {
      setGoldApprovalResult({ status: 'ERROR', reason: 'request failed' })
    } finally {
      setGoldApprovalBusy(false)
      const response = await fetch('/api/gold-status'); if (response.ok) setGold(await response.json())
    }
  }
  const decideBtcPending = async (action: 'approve' | 'reject') => {
    setBtcApprovalBusy(true)
    try {
      const response = await fetch(`/api/btctrend-${action}`, { method: 'POST' })
      setBtcApprovalResult(response.ok ? await response.json() : { status: 'ERROR', reason: 'request failed' })
    } catch {
      setBtcApprovalResult({ status: 'ERROR', reason: 'request failed' })
    } finally {
      setBtcApprovalBusy(false)
      const response = await fetch('/api/btctrend-status'); if (response.ok) setBtc(await response.json())
    }
  }

  return <main className={isMobile ? 'mobile-layout' : ''}>
    {isMobile ? (
      <header className="mobile-topbar"><div className="brand"><span className="brand-mark"><Activity size={18} /></span><span>Northstar</span></div><div className="status-badge"><span className={data?.scheduler.active ? 'live' : 'idle'}>{data?.scheduler.active ? '●' : '○'}</span></div></header>
    ) : (
      <header className="topbar"><div className="brand"><span className="brand-mark"><Activity size={20} /></span><span>Northstar</span><small>AUTOMATED TRADING STRATEGY</small></div><div className={`connection connection-${(view === 'WHEEL' ? wheel?.connection_mode : view === 'GOLD' ? gold?.connection_mode : view === 'BULLSPREAD' ? bullSpread?.connection_mode : view === 'BTC' ? btc?.connection_mode : 'paper') ?? 'unknown'}`}><span className="pulse" /> IBKR {(view === 'WHEEL' ? wheel?.connection_mode : view === 'GOLD' ? gold?.connection_mode : view === 'BULLSPREAD' ? bullSpread?.connection_mode : view === 'BTC' ? btc?.connection_mode : 'paper')?.toUpperCase() ?? 'UNKNOWN'} <span className="divider" /> <Clock3 size={15} /> {view === 'EQUITY' ? `${data?.scheduler.interval_minutes ?? 30} MIN EQUITY CYCLE` : view === 'WHEEL' ? '30 MIN OPTIONS CYCLE' : view === 'GOLD' ? '30 MIN GOLD CYCLE' : view === 'BTC' ? `${btc?.scheduler?.interval_minutes ?? 5} MIN BTC CYCLE · 24/7` : 'MANUAL RESEARCH TOOL'}</div></header>
    )}
    {!isMobile && <div className="view-toggle"><button className={view === 'EQUITY' ? 'selected' : ''} onClick={() => setView('EQUITY')}>Equity Signals</button><button className={view === 'WHEEL' ? 'selected' : ''} onClick={() => setView('WHEEL')}>Options Wheel</button><button className={view === 'GOLD' ? 'selected' : ''} onClick={() => setView('GOLD')}>Gold Carry</button><button className={view === 'BULLSPREAD' ? 'selected' : ''} onClick={() => setView('BULLSPREAD')}>MS Bull Call Spread</button><button className={view === 'BTC' ? 'selected' : ''} onClick={() => setView('BTC')}>BTC Trend</button></div>}

    {view === 'EQUITY' && <><StrategyHero active={data?.scheduler.active} title="Equity signal operations" subhead="News ingestion, signal scoring, fair allocation, and paper-broker execution." ytdPnl={data?.ytd_realized_pnl} nextLabel="NEXT NEWS SWEEP" nextValue={data?.scheduler.next_poll ?? null} lastValue={clock(data?.scheduler.last_sweep_started_at ?? null)} lastNote={`cycle took ${duration(data?.scheduler.last_sweep_duration_seconds ?? null)}`} />
      <section className="panel strategy-rules"><div><p className="eyebrow">HOW EQUITY SIGNALS WORK</p><h2>Decision and execution rules</h2></div><div className="wheel-rules-grid"><div><strong>Ingest and score</strong><span>Provider news from the past 7 days is deduplicated, keyword-scored, recency-weighted, and combined with market context.</span></div><div><strong>Buy quality gate</strong><span>BUY needs positive combined score plus primary/professional evidence or two independent secondary sources.</span></div><div><strong>Risk and exits</strong><span>Selected buys use 20 shares, 30% daily budget, 50% gross cap, and a +6% target / -3% stop bracket.</span></div></div></section>
      <section className="metrics"><article><div className="metric-icon blue"><Radio size={19} /></div><div><span>WATCHLIST COVERAGE</span><strong>{data?.summary.symbols ?? 0}<em> symbols</em></strong></div></article><article><div className="metric-icon gold"><Bell size={19} /></div><div><span>NEWS IN LATEST BATCHES</span><strong>{data?.summary.articles?.toLocaleString() ?? 0}<em> articles</em></strong></div></article><article><div className="metric-icon green"><ArrowUpRight size={19} /></div><div><span>ACTIONABLE BUYS</span><strong>{data?.summary.buy_signals ?? 0}<em> signals</em></strong></div></article><article><div className="metric-icon red"><ArrowDownRight size={19} /></div><div><span>SELL / EXIT FLAGS</span><strong>{data?.summary.sell_signals ?? 0}<em> signals</em></strong></div></article></section>
      <section className="panel signal-panel"><div className="panel-header"><div><p className="eyebrow">SIGNAL MONITOR</p><h2>Current market read</h2></div></div><div className="signal-table"><div className="table-head"><span>SYMBOL</span><span>NEWS</span><span>CONVICTION</span><span>MARKET CONTEXT</span><span>DECISION</span></div>{data?.symbols.map((item) => <button className="signal-row" key={item.symbol} onClick={() => { setSelectedSignal(item.symbol); setShown(10) }} title={`Inspect ${item.symbol} contribution details`}><div className="company"><strong>{item.symbol}</strong><span>{item.name} <i>{item.exchange}</i></span></div><div className="news-count"><strong>{item.articles}</strong><span>{item.sources} sources · inspect</span></div><div className="conviction"><strong>{item.confidence == null ? '---' : `${Math.round(item.confidence * 100)}%`}</strong><span className={(item.sentiment ?? 0) >= 0 ? 'positive' : 'negative'}>{item.sentiment?.toFixed(2) ?? '---'} sentiment</span></div><div className="market"><strong>{money(item.price)}</strong><span>{item.trend}</span></div><div><span className={`signal-pill ${item.decision.toLowerCase()}`}>{item.decision}</span><small className="urgency">{item.urgency}</small></div></button>)}</div></section>
      <section className="panel pnl-panel"><div className="panel-header"><div><p className="eyebrow">REALIZED P&amp;L</p><h2>Realized P&amp;L by ticker, year to date</h2></div><span className="last-refresh">From IBKR closing fills of strategy orders</span></div><div className="pnl-grid"><div className="pnl-head"><span>SYMBOL</span><span>CLOSING FILLS</span><span>LAST EXIT</span><span>SOURCE</span><span>REALIZED P&amp;L</span></div>{(data?.realized_by_symbol ?? []).map((row) => <div className="pnl-row" key={row.symbol}><strong>{row.symbol}</strong><span>{row.closing_fills}</span><span>{dateTime(row.last_exit)}</span><span>{row.reconstructed ? 'Includes backfilled amount' : 'IBKR fills'}</span><strong className={row.realized_pnl >= 0 ? 'positive' : 'negative'}>{money(row.realized_pnl)}</strong></div>)}{data?.realized_by_symbol?.length ? <div className="pnl-row pnl-total"><strong>Total</strong><span>{data.realized_by_symbol.reduce((count, row) => count + row.closing_fills, 0)}</span><span /><span /><strong className={(data.ytd_realized_pnl ?? 0) >= 0 ? 'positive' : 'negative'}>{money(data.ytd_realized_pnl)}</strong></div> : <div className="empty">No realized P&amp;L recorded this year.</div>}</div></section>
      <section className="panel execution-panel"><div className="panel-header"><div><p className="eyebrow">BROKER ACTIVITY</p><h2>Order events, past 3 days</h2></div><div className="event-tools"><select value={status} onChange={(event) => { setStatus(event.target.value); setEventPage(0) }}>{statuses.map((item) => <option key={item}>{item}</option>)}</select><span className="last-refresh">Updated {dateTime(data?.generated_at ?? null)}</span></div></div><div className="execution-grid"><div className="exec-head"><span>TIME</span><span>SYMBOL</span><span>ORDER</span><span>STATUS</span><span>DETAIL</span></div>{visibleEvents.map((event) => <button className="exec-row" key={event.event_id} onClick={() => setSelectedOrder(event)}><span>{dateTime(event.timestamp)}</span><strong>{event.symbol}</strong><span>{event.action ?? 'ORDER'} {event.requested_qty} @ {money(event.price ?? event.bracket.entry_limit)}</span><span className={`status ${event.status.toLowerCase()}`}>{event.status}</span><span>{event.filled_qty ? `${event.filled_qty} filled` : event.reasons[0] ?? 'Inspect order'}</span></button>)}{!events.length && <div className="empty">No order events match this status.</div>}</div>{events.length > 10 && <div className="event-pagination"><button disabled={eventPage === 0} onClick={() => setEventPage((page) => page - 1)}>Previous</button><span>Page {eventPage + 1} of {eventPages}</span><button disabled={eventPage >= eventPages - 1} onClick={() => setEventPage((page) => page + 1)}>Next</button></div>}</section>
      <section className="audit-section"><div className="audit-heading"><div><p className="eyebrow">NEWS-TO-ORDER AUDIT</p><h2>Top contribution to signal</h2><p>Ranked by absolute impact. Expand each article for score math.</p></div></div><div className="audit-layout"><aside className="panel run-list"><div className="list-label">RECENT POLL RUNS</div>{runs.map((run) => <button key={run.run_id} className={audit?.run_id === run.run_id ? 'run-row active' : 'run-row'} onClick={() => void selectRun(run.run_id)}><span><strong>{dateTime(run.started_at)}</strong><small>{run.retained_articles} retained</small></span><ChevronRight size={14} /></button>)}</aside><div className="audit-detail"><section className="panel trace-summary"><div className="symbol-tabs">{Object.keys(audit?.symbols ?? {}).map((item) => <button key={item} className={symbol === item ? 'selected' : ''} onClick={() => setSymbol(item)}>{item}</button>)}</div></section><section className="panel article-panel"><div className="panel-header"><div><p className="eyebrow">ARTICLE EVIDENCE</p><h2>{symbol || 'Symbol'} contributions</h2></div><span className="last-refresh">Showing {Math.min(shown, articles.length)} of {articles.length}</span></div>{articles.slice(0, shown).map((article, index) => <article className="audit-article" key={`${article.article_id}-${index}`}><div className="article-top"><div><span className={`article-sentiment ${article.sentiment}`}>{article.sentiment}</span><strong>{article.title}</strong></div>{article.url && <a href={article.url} target="_blank" rel="noreferrer"><ExternalLink size={16} /></a>}</div><p>{article.summary}</p><div className="article-meta"><span>{article.source}</span><span>{article.topic}</span><span>contribution {article.sentiment_contribution?.toFixed(4) ?? '---'}</span></div><ScoreMath article={article} /></article>)}{articles.length > shown && <button className="show-more" onClick={() => setShown((count) => count + 10)}>Show 10 more contributions</button>}</section></div></div></section>
    </>}
    {view === 'WHEEL' && <><StrategyHero active={wheel?.scheduler?.active} title="Wheel strategy operations" subhead="Cash-secured puts, assignment-aware covered calls, and stock-pool separation for GOOGL and VOO." ytdPnl={wheel?.ytd_realized_pnl} nextLabel="NEXT WHEEL SCAN" nextValue={wheel?.scheduler?.next_run ?? null} lastValue={clock(wheel?.scheduler?.last_run_at ?? null)} lastNote={`IBKR ${wheel?.connection_mode ?? 'unavailable'} · every 30 min`} />
      {Object.entries(wheel?.pending_approvals ?? {}).map(([symbol, pending]) => <section className="panel approval-panel" key={symbol}><div className="panel-header"><div><p className="eyebrow">HUMAN REVIEW REQUIRED</p><h2>{symbol} order awaiting approval</h2></div><span className="last-refresh">expires {clock(pending.expires_at)}</span></div>
        <div className="order-detail-grid"><div><span>ACTION</span><strong>{pending.recommendation.action}</strong></div><div><span>CONTRACTS</span><strong>{pending.recommendation.contracts}</strong></div><div><span>STRUCTURE</span><strong>{pending.recommendation.contract ? `${pending.recommendation.contract.right === 'P' ? 'PUT' : 'CALL'} $${pending.recommendation.contract.strike} · ${pending.recommendation.contract.expiry}` : '---'}</strong></div><div><span>PREMIUM / COLLATERAL</span><strong>{money(pending.recommendation.premium_credit)} / {money(pending.recommendation.collateral_required)}</strong></div></div>
        {!!pending.recommendation.reasons.length && <details className="score-math" open><summary>Why this order</summary><div>{pending.recommendation.reasons.map((reason, index) => <p key={index}>{reason}</p>)}</div></details>}
        <div className="approval-actions">
          <button className="approve-btn" disabled={wheelApprovalBusy === symbol} onClick={() => void decideWheelPending(symbol, 'approve')}>Approve &amp; submit to IBKR</button>
          <button className="reject-btn" disabled={wheelApprovalBusy === symbol} onClick={() => void decideWheelPending(symbol, 'reject')}>Reject</button>
        </div>
        {wheelApprovalResult[symbol] && <p className={wheelApprovalResult[symbol].status === 'REJECTED' || wheelApprovalResult[symbol].status === 'ERROR' ? 'exit-signal-note' : 'positive'}>{wheelApprovalResult[symbol].status}{wheelApprovalResult[symbol].reason ? ` — ${wheelApprovalResult[symbol].reason}` : ''}</p>}
      </section>)}
      <section className="panel strategy-rules"><div><p className="eyebrow">HOW THE WHEEL WORKS</p><h2>Entry and transition rules</h2></div><div className="wheel-rules-grid"><div><strong>Short put</strong><span>Fewer than 100 registered wheel shares, 21-45 DTE, about 5% OTM (3% for VOO), |delta| 0.15-0.30, 8%+ annualized yield, and collateral under 10% of net liquidation.</span></div><div><strong>Short call</strong><span>At least 100 registered assigned shares. External equity-signal shares do not cover a wheel call.</span></div><div><strong>Stock pool</strong><span>A registered assigned lot moves to pool once price is 10% below assignment strike. Pool shares stay outside covered calls.</span></div></div></section><section className="panel wheel-panel"><div className="wheel-head"><span>SYMBOL</span><span>MARKET / STOCK</span><span>OPEN WHEEL OPTION</span><span>STOCK POOL</span><span>STATE</span></div>{wheel?.symbols.map((item) => { const options = item.open_options.length ? item.open_options : (item.tracked_options ?? []).map((option) => ({ ...option, side: 'SHORT' })); const latest = wheel.latest_runs?.[item.symbol]; return <button className="wheel-row" key={item.symbol} onClick={() => setSelectedWheel(item)} title={`Inspect ${item.symbol} wheel status`}><div><strong>{item.symbol}</strong><span>{wheel?.connection_mode ?? 'unavailable'} automated</span></div><div><strong>{money(item.market_price)}</strong>{item.stock_shares > 0 ? <span>{item.stock_shares} wheel-assigned @ {money(item.stock_average_cost)}</span> : <span>No wheel-assigned stock</span>}{item.external_shares > 0 && <span className="external-note">{item.external_shares} external shares excluded</span>}</div><div>{options.length ? options.map((option, index) => <span className="option-line" key={index}>{option.side} {option.right === 'P' ? 'PUT' : 'CALL'} {option.contracts}x ${option.strike} · {option.expiry} · premium {money(option.premium)}</span>) : <span>{latest?.status === 'data_unavailable' ? 'Option data unavailable' : 'No open option'}</span>}</div><div>{item.stock_pool.shares ? <><strong>{item.stock_pool.shares} shares</strong><span>avg cost {money(item.stock_pool.average_cost)}</span></> : <span>No pooled stock</span>}</div><div><span className={item.stock_pool.shares ? 'pool-pill' : 'wheel-pill'}>{item.stock_pool.shares ? 'STOCK_POOL' : item.active_wheel_shares >= 100 ? 'COVERED CALL READY' : 'PUT WHEEL READY'}</span></div></button> })}</section></>}
    {view === 'GOLD' && <><StrategyHero active={gold?.scheduler?.active} title="Gold carry operations" subhead="Spot-vs-futures cash-and-carry and MGC calendar spreads, entered only when a carry-cost-adjusted edge clears transaction costs." ytdPnl={gold?.ytd_realized_pnl} nextLabel="NEXT GOLD SCAN" nextValue={gold?.scheduler?.next_run ?? null} lastValue={clock(gold?.scheduler?.last_run_at ?? null)} lastNote={`IBKR ${gold?.connection_mode ?? 'unavailable'} · every 30 min`} />
      {gold?.pending_approval && <section className="panel approval-panel"><div className="panel-header"><div><p className="eyebrow">HUMAN REVIEW REQUIRED</p><h2>{gold.pending_approval.kind === 'exit' ? 'Gold position exit awaiting approval' : gold.pending_approval.kind === 'entry_cash_and_carry' ? 'Cash-and-carry entry awaiting approval' : 'Calendar spread entry awaiting approval'}</h2></div><span className="last-refresh">expires {clock(gold.pending_approval.expires_at)}</span></div>
        {gold.pending_approval.kind === 'exit' ? <p>{gold.pending_approval.payload.reason}</p> : <div className="order-detail-grid"><div><span>ACTION</span><strong>{gold.pending_approval.payload.recommendation?.action}</strong></div><div><span>NET EDGE AFTER COSTS</span><strong>{money(gold.pending_approval.payload.recommendation?.net_edge_after_costs ?? null)}</strong></div></div>}
        {!!gold.pending_approval.payload.recommendation?.reasons?.length && <details className="score-math" open><summary>Why this order</summary><div>{gold.pending_approval.payload.recommendation.reasons.map((reason, index) => <p key={index}>{reason}</p>)}</div></details>}
        <div className="approval-actions">
          <button className="approve-btn" disabled={goldApprovalBusy} onClick={() => void decideGoldPending('approve')}>Approve &amp; submit to IBKR</button>
          <button className="reject-btn" disabled={goldApprovalBusy} onClick={() => void decideGoldPending('reject')}>Reject</button>
        </div>
        {goldApprovalResult && <p className={goldApprovalResult.status === 'REJECTED' || goldApprovalResult.status === 'ERROR' ? 'exit-signal-note' : 'positive'}>{goldApprovalResult.status}{goldApprovalResult.reason ? ` — ${goldApprovalResult.reason}` : ''}</p>}
      </section>}
      <section className="panel strategy-rules"><div><p className="eyebrow">HOW GOLD CARRY WORKS</p><h2>Entry and exit rules</h2></div><div className="wheel-rules-grid"><div><strong>Cash-and-carry</strong><span>Long US Spot Gold (XAUUSD), short Micro Gold futures (MGC) once the futures price exceeds carry-cost fair value by at least 0.15% of notional, net of estimated costs. The reverse (short spot) direction is never traded.</span></div><div><strong>Calendar spread</strong><span>Front vs. next active MGC month via a combo order, traded in either direction once the mispricing clears the same net-edge floor.</span></div><div><strong>Risk caps</strong><span>One open position at a time, 20% of net liquidation per trade, 70%-of-edge profit target, 2x-of-edge stop-loss, and exit before the near month's last trading day.</span></div></div></section><section className="panel wheel-panel"><div className="wheel-head"><span>INSTRUMENT</span><span>BID / ASK</span><span>DAYS TO EXPIRY</span><span>LATEST RECOMMENDATION</span><span>STATE</span></div><div className="wheel-row"><div><strong>Spot XAUUSD</strong><span>{gold?.connection_mode ?? 'unavailable'}</span></div><div><strong>{money(gold?.spot?.bid ?? null)} / {money(gold?.spot?.ask ?? null)}</strong></div><div><span>---</span></div><div><span>{gold?.latest_run?.status === 'data_unavailable' ? 'Data unavailable' : gold?.latest_run?.cash_and_carry?.recommendation.action ?? 'No run yet'}</span></div><div><span className="wheel-pill">SPOT</span></div></div><div className="wheel-row"><div><strong>MGC {gold?.near_future?.expiry ?? '---'}</strong><span>near month</span></div><div><strong>{money(gold?.near_future?.bid ?? null)} / {money(gold?.near_future?.ask ?? null)}</strong></div><div><strong>{gold?.near_future?.days_to_expiry ?? '---'}</strong></div><div><span>{gold?.latest_run?.cash_and_carry?.recommendation.net_edge_after_costs != null ? `net edge ${money(gold.latest_run.cash_and_carry.recommendation.net_edge_after_costs)}` : '---'}</span></div><div><span className="wheel-pill">NEAR</span></div></div><div className="wheel-row"><div><strong>MGC {gold?.far_future?.expiry ?? '---'}</strong><span>far month</span></div><div><strong>{money(gold?.far_future?.bid ?? null)} / {money(gold?.far_future?.ask ?? null)}</strong></div><div><strong>{gold?.far_future?.days_to_expiry ?? '---'}</strong></div><div><span>{gold?.latest_run?.calendar_spread?.recommendation.action ?? '---'}</span></div><div><span className="wheel-pill">FAR</span></div></div></section><section className="panel calc-panel"><div className="panel-header"><div><p className="eyebrow">DETAILED CALCULATION</p><h2>Cost of carry &amp; arbitrage justification</h2></div></div><div className="gold-calc"><details className="score-math" open><summary>Cash-and-carry: spot vs near month ({gold?.near_future?.expiry ?? '---'})</summary><div><LadderBreakdown ladder={goldCarryRec?.ladder} label={`Spot ${gold?.spot?.bid != null ? '(live)' : ''} → MGC ${gold?.near_future?.expiry ?? '---'}`} /><ArbitrageVerdict rec={goldCarryRec} /></div></details><details className="score-math" open><summary>Calendar spread: near ({gold?.near_future?.expiry ?? '---'}) vs far ({gold?.far_future?.expiry ?? '---'})</summary><div><LadderBreakdown ladder={goldCalendarRec?.near_ladder} label={`Near leg: spot → MGC ${gold?.near_future?.expiry ?? '---'}`} /><LadderBreakdown ladder={goldCalendarRec?.far_ladder} label={`Far leg: spot → MGC ${gold?.far_future?.expiry ?? '---'}`} /><p><b>Fair spread:</b> far theoretical {money(goldCalendarRec?.theoretical_spread ?? goldCalendarRec?.far_ladder?.theoretical_price)} − near theoretical {money(goldCalendarRec?.near_ladder?.theoretical_price)} = <strong>{money4(goldCalendarRec?.theoretical_spread)}</strong></p><p><b>Market spread:</b> far {money(gold?.far_future?.bid)} − near {money(gold?.near_future?.bid)} = <strong>{money4(goldCalendarRec?.market_spread)}</strong></p><p><b>Mispricing:</b> market spread − fair spread = <strong>{money4(goldCalendarRec?.mispricing)}</strong></p><ArbitrageVerdict rec={goldCalendarRec} /></div></details></div></section><section className="panel wheel-panel"><div className="wheel-head"><span>POSITION</span><span>LEGS</span><span>ENTRY EDGE</span><span>OPENED</span><span>STATE</span></div>{gold?.open_positions.map((position) => <div className="wheel-row" key={position.id}><div><strong>{position.type === 'cash_and_carry' ? 'Cash-and-carry' : 'Calendar spread'}</strong><span>{position.action}</span></div><div>{position.legs.map((leg, index) => <span className="option-line" key={index}>{leg.action} {leg.quantity} {leg.contract}</span>)}</div><div><strong>{money(position.entry_net_edge)}</strong></div><div><span>{dateTime(position.opened_at)}</span></div><div><span className="wheel-pill">{position.status.toUpperCase()}</span></div></div>)}{!gold?.open_positions.length && <div className="empty">No open gold position.</div>}</section></>}
    {view === 'BULLSPREAD' && <><StrategyHero active={bullSpread?.scheduler?.active} title="MS bull call spread research" subhead="Automated research every 30 min during options trading hours: picks the best long/short call pair for a target price and date, then sizes it by dollar amount. Execution and exit remain manual." ytdPnl={0} nextLabel="NEXT BULLSPREAD SCAN" nextValue={bullSpread?.scheduler?.next_run ?? null} lastValue={clock(bullSpread?.scheduler?.last_run_at ?? null)} lastNote={`IBKR ${bullSpread?.connection_mode ?? 'paper'} (or yfinance fallback) · every 30 min, Mon-Fri 9:30am-4:00pm ET`} /><section className="panel strategy-rules"><div><p className="eyebrow">HOW THE BULL CALL SPREAD TOOL WORKS</p><h2>Selection, sizing, and exit rules</h2></div><div className="wheel-rules-grid"><div><strong>Expiration</strong><span>Only quarterly-cycle expirations (Jan/Apr/Jul/Oct) at or after your target date are considered.</span></div><div><strong>Strikes</strong><span>Long call closest to (not above) spot; short call at/above your target price, chosen for the best return-on-debit among strikes with a tradable (non-stale) quote.</span></div><div><strong>Sizing and exit</strong><span>Contracts = floor(amount / (net debit x 100 + costs)), capped at 20% of net liquidation. Suggested exit: close at 50% of entry debit lost, or 7 days before expiry &mdash; advisory only, never auto-executed.</span></div></div></section>
      {analystPrediction && <section className="panel calc-panel"><div className="panel-header"><div><p className="eyebrow">AGENT REASONING</p><h2>MS stock analyst agent &mdash; earnings-day price prediction</h2></div></div>
        <div className="order-detail-grid"><div><span>YOUR FORECAST CONFIDENCE</span><strong>{analystPrediction.input_confidence_pct}%</strong></div><div><span>EARNINGS DATE</span><strong>{analystPrediction.earnings_date}</strong></div><div><span>PREDICTED PRICE</span><strong>{money(analystPrediction.predicted_price)}</strong></div><div><span>PREDICTED RANGE</span><strong>{money(analystPrediction.price_range_low)}&ndash;{money(analystPrediction.price_range_high)}</strong></div><div><span>AGENT'S REACTION CONFIDENCE</span><strong>{analystPrediction.confidence.toUpperCase()}</strong></div><div><span>PREDICTED EPS</span><strong>{analystPrediction.predicted_eps != null ? `$${analystPrediction.predicted_eps}` : '---'}</strong></div><div><span>IMPLIED SURPRISE VS. CONSENSUS</span><strong className={(analystPrediction.implied_surprise_pct ?? 0) >= 0 ? 'positive' : 'negative'}>{analystPrediction.implied_surprise_pct != null ? `${analystPrediction.implied_surprise_pct > 0 ? '+' : ''}${analystPrediction.implied_surprise_pct}%` : '---'}</strong></div></div>
        <div className="gold-calc">{consensusSnapshot && <div className="score-math"><p className="ladder-label">Consensus EPS by source (corroboration check)</p><p><b>yfinance:</b> {money(consensusSnapshot.consensus_eps)} (range {money(consensusSnapshot.eps_low)}&ndash;{money(consensusSnapshot.eps_high)})</p><p><b>Nasdaq:</b> {consensusSnapshot.nasdaq_forecast ? <>{money(consensusSnapshot.nasdaq_forecast.consensus_eps)} (range {money(consensusSnapshot.nasdaq_forecast.eps_low)}&ndash;{money(consensusSnapshot.nasdaq_forecast.eps_high)}, {consensusSnapshot.nasdaq_forecast.num_estimates} estimates, fiscal Q end {consensusSnapshot.nasdaq_forecast.fiscal_quarter_end})</> : 'unavailable for this run'}</p><p><b>Analyst price targets:</b> mean {money(consensusSnapshot.analyst_target_mean)}, median {money(consensusSnapshot.analyst_target_median)}</p></div>}<div className="score-math"><p className="ladder-label">Consensus summary</p><p>{analystPrediction.consensus_summary}</p><p className="ladder-label" style={{ marginTop: 12 }}>Full reasoning</p>{analystPrediction.reasoning.map((reason, index) => <p key={index}>&bull; {reason}</p>)}</div></div></section>}
      {tradingAgent && <section className="panel calc-panel"><div className="panel-header"><div><p className="eyebrow">AGENT REASONING</p><h2>Bull call spread trading agent</h2></div></div><div className="gold-calc"><div className="score-math">{tradingAgent.reasoning.map((reason, index) => <p key={index}>&bull; {reason}</p>)}{!!tradingAgent.alternatives_considered.length && <><p className="ladder-label" style={{ marginTop: 10 }}>Alternatives considered</p>{tradingAgent.alternatives_considered.map((alt, index) => <p key={index}>&bull; {alt}</p>)}</>}<p className="exit-signal-note" style={{ marginTop: 10 }}>Primary risk: {tradingAgent.primary_risk}</p></div></div></section>}
      <section className="panel wheel-panel"><div className="wheel-head"><span>STRUCTURE</span><span>NET DEBIT / CONTRACTS</span><span>MAX PROFIT / LOSS</span><span>BREAKEVEN</span><span>STATE</span></div>{bullSpreadRec ? <div className="wheel-row"><div><strong>{bullSpreadRec.symbol} {bullSpreadRec.long_leg?.strike} / {bullSpreadRec.short_leg?.strike} calls</strong><span>exp {bullSpreadRec.expiry} &middot; target {money(bullSpreadRec.target_price)} by {bullSpreadRec.target_date}</span></div><div><strong>{money(bullSpreadRec.net_debit)}</strong><span>{bullSpreadRec.contracts} contract(s)</span></div><div><strong className="positive">{money(bullSpreadRec.max_profit)}</strong><span className="negative">{money(bullSpreadRec.max_loss ? -bullSpreadRec.max_loss : null)}</span></div><div><strong>{money(bullSpreadRec.breakeven)}</strong><span>{bullSpreadRec.return_on_debit_pct?.toFixed(1)}% return on debit</span></div><div><span className="wheel-pill">{bullSpreadRec.action}</span></div></div> : <div className="empty">No recommendation yet &mdash; run run_bullcallspread.py.</div>}</section>
      <section className="panel calc-panel"><div className="panel-header"><div><p className="eyebrow">PAYOFF PROJECTION</p><h2>Profit &amp; loss across price scenarios</h2></div></div><div className="gold-calc">{bullSpreadRec ? <div className="score-math"><PayoffChart rec={bullSpreadRec} spot={bullSpread?.latest_recommendation?.spot_price} /><div className="payoff-ladder-legend">{bullSpreadRec.payoff_ladder.map((point, index) => <span key={index}><b>{point.label}</b> ({money(point.price)}): <strong className={point.profit_loss >= 0 ? 'positive' : 'negative'}>{money(point.profit_loss)}</strong></span>)}</div></div> : <p>No payoff data available &mdash; run run_bullcallspread.py.</p>}{bullSpreadRec?.exit_plan && <details className="score-math" open><summary>Suggested exit plan (advisory, not auto-executed)</summary><div>{bullSpreadRec.exit_plan.notes.map((note, index) => <p key={index}>{note}</p>)}</div></details>}{!!bullSpreadRec?.reasons.length && <details className="score-math"><summary>Reasoning</summary><div>{bullSpreadRec.reasons.map((reason, index) => <p key={index}>{reason}</p>)}</div></details>}</div></section>
      <section className="panel wheel-panel"><div className="wheel-head"><span>POSITION</span><span>LEGS</span><span>ENTRY DEBIT</span><span>OPENED</span><span>STATE</span></div>{bullSpread?.open_positions.map((position) => <div className="wheel-row" key={position.id}><div><strong>{position.symbol} bull call spread</strong><span>{position.contracts} contract(s)</span></div><div>{position.legs.map((leg, index) => <span className="option-line" key={index}>{leg.action} {leg.strike} call &middot; {leg.expiry}</span>)}</div><div><strong>{money(position.entry_net_debit)}</strong></div><div><span>{dateTime(position.opened_at)}</span></div><div><span className="wheel-pill">{position.status.toUpperCase()}</span></div></div>)}{!bullSpread?.open_positions.length && <div className="empty">No open bull call spread position.</div>}</section>
      {!!bullSpread?.open_positions.length && <section className="panel calc-panel"><div className="panel-header"><div><p className="eyebrow">LIVE POSITION TRACKING</p><h2>Actual unrealized P&amp;L</h2></div></div><div className="gold-calc">{bullSpread.open_positions.map((position) => <div className="score-math" key={position.id}><p className="ladder-label">{position.symbol} {position.legs.find((l) => l.action === 'BUY')?.strike}/{position.legs.find((l) => l.action === 'SELL')?.strike} &middot; opened {dateTime(position.opened_at)}</p><UnrealizedPnlChart history={position.pnl_history ?? []} /></div>)}</div></section>}</>}
    {view === 'BTC' && <><StrategyHero active={btc?.scheduler?.active} title="Bitcoin trend following" subhead="A 9-signal medium-horizon trend ensemble, scaled by a volatility target and rebalanced only on meaningful changes. Long-only BTC (Paxos) with a 4x ATR trailing stop and a one-time profit trim." ytdPnl={btc?.ytd_realized_pnl} nextLabel="NEXT BTC CYCLE" nextValue={btc?.scheduler?.next_run ?? null} lastValue={clock(btc?.scheduler?.last_run_at ?? null)} lastNote={`IBKR ${btc?.connection_mode ?? 'paper'} · every ${btc?.scheduler?.interval_minutes ?? 5} min, 24/7 · stop checked every cycle`} />
      <section className="panel strategy-rules"><div><p className="eyebrow">HOW BTC TREND WORKS</p><h2>Signal, sizing and exit rules</h2></div><div className="wheel-rules-grid"><div><strong>Ensemble signal</strong><span>Nine 0/1 votes on completed daily bars: close vs SMA 50/100/150, SMA 20/100 and 50/200 crosses, 60/120-day momentum, Donchian 55/20 and 100/50. Score = fraction long.</span></div><div><strong>Sizing</strong><span>Target = score x min(1, 60% / 30-day vol) of a sleeve worth 10% of excess liquidity. Never levered, long-only, keeps a 5% cash reserve.</span></div><div><strong>Exits and profit taking</strong><span>Signal exit when votes turn flat; trailing stop at the peak close since entry minus 4x 14-day ATR, checked against the live bid every cycle (after a stop, flat until a new 20-day high). Trims a third once a close is +50% over entry. Stale data blocks increases.</span></div></div></section>
      {(btcRun?.status === 'data_unavailable' || btcRun?.status === 'error') && <p className="exit-signal-note">Latest cycle {dateTime(btcRun.generated_at ?? null)}: {btcRun.status.replace('_', ' ')} &mdash; {btcRun.reason}</p>}
      {btcRun?.data?.stale && <p className="exit-signal-note">Daily data is stale: newest completed bar is {btcRun.data.last_bar} ({btcRun.data.bar_age_days} day(s) behind). Increases are blocked until it updates; exits still run.</p>}
      {btc?.scheduler?.stale && <p className="exit-signal-note">Scheduler is running but the last cycle was {dateTime(btc.scheduler.last_run_at)} &mdash; more than three intervals ago. Cycles may be failing or hung; the trailing stop is not being checked.</p>}
      {btcPending && <section className="panel approval-panel"><div className="panel-header"><div><p className="eyebrow">HUMAN REVIEW REQUIRED</p><h2>Pending BTC order awaiting approval</h2></div><span className="last-refresh">expires {clock(btcPending.expires_at)}</span></div>
        <div className="order-detail-grid"><div><span>ACTION</span><strong>{btcPending.recommendation.action}</strong></div><div><span>QUANTITY</span><strong>{btcPending.recommendation.order_qty.toFixed(4)} BTC</strong></div><div><span>LIMIT PRICE</span><strong>{money(btcPending.recommendation.limit_price)}</strong></div><div><span>NOTIONAL</span><strong>{money(btcPending.recommendation.order_notional)}</strong></div></div>
        {!!btcPending.recommendation.reasons.length && <details className="score-math" open><summary>Why this order</summary><div>{btcPending.recommendation.reasons.map((reason, index) => <p key={index}>{reason}</p>)}</div></details>}
        <div className="approval-actions">
          <button className="approve-btn" disabled={btcApprovalBusy} onClick={() => void decideBtcPending('approve')}>Approve &amp; submit to IBKR</button>
          <button className="reject-btn" disabled={btcApprovalBusy} onClick={() => void decideBtcPending('reject')}>Reject</button>
        </div>
        {btcApprovalResult && <p className={btcApprovalResult.status === 'REJECTED' || btcApprovalResult.status === 'ERROR' ? 'exit-signal-note' : 'positive'}>{btcApprovalResult.status}{btcApprovalResult.reason ? ` — ${btcApprovalResult.reason}` : ''}</p>}
      </section>}
      <section className="metrics"><article><div className="metric-icon blue"><Radio size={19} /></div><div><span>ENSEMBLE SCORE</span><strong>{btcSignal ? `${btcSignal.votes.filter((vote) => vote.long).length}/${btcSignal.votes.length}` : '---'}<em> long votes</em></strong></div></article><article><div className="metric-icon gold"><Activity size={19} /></div><div><span>30-DAY VOLATILITY</span><strong>{btcSignal ? (btcSignal.realized_vol_annual * 100).toFixed(0) : '---'}<em>% ann. &middot; scalar {btcSignal?.vol_scalar.toFixed(2) ?? '---'}</em></strong></div></article><article><div className="metric-icon green"><ArrowUpRight size={19} /></div><div><span>TARGET EXPOSURE</span><strong>{btcSignal ? (btcSignal.target_exposure * 100).toFixed(0) : '---'}<em>% of sleeve</em></strong></div></article><article><div className="metric-icon red"><ArrowDownRight size={19} /></div><div><span>HELD EXPOSURE</span><strong>{btcPosition ? (btcPosition.held_exposure * 100).toFixed(0) : '---'}<em>% committed</em></strong></div></article></section>
      <section className="panel calc-panel"><div className="panel-header"><div><p className="eyebrow">PRICE CHART</p><h2>BTC close with trend signal inputs</h2></div><span className="last-refresh">daily bars, refreshed every 5 min</span></div><BtcPriceChart bars={btcBars} stopPrice={btcRec?.stop_price} suggestedStopPrice={btcRec?.stop_price_if_filled} /></section>
      <section className="panel signal-panel"><div className="panel-header"><div><p className="eyebrow">SIGNAL MONITOR</p><h2>Ensemble votes{btcSignal ? ` at the ${btcSignal.bar_date} close (${money(btcSignal.close)})` : ''}</h2></div>{btcSignal && <span className="last-refresh">30-day return {btcSignal.return_30d_pct.toFixed(1)}% &middot; {btcSignal.drawdown_from_high_pct.toFixed(1)}% from high</span>}</div>
        <div className="btc-table"><div className="btc-vote-head"><span>SIGNAL</span><span>VOTE</span><span>INPUTS</span></div>{btcSignal ? btcSignal.votes.map((vote) => <div className="btc-vote-row" key={vote.name}><strong>{vote.name}</strong><span><span className={`signal-pill ${vote.long ? 'buy' : 'hold'}`}>{vote.long ? 'LONG' : 'FLAT'}</span></span><span>{vote.detail}</span></div>) : <div className="empty">No signal yet &mdash; run python -m btctrend.run_btctrend.</div>}</div></section>
      <section className="panel wheel-panel"><div className="wheel-head"><span>DECISION</span><span>ORDER</span><span>SLEEVE / TARGET</span><span>EXECUTION</span><span>STATE</span></div>{btcRec ? <div className="wheel-row"><div><strong>{btcRec.action}</strong><span>held {(btcRec.held_exposure_before * 100).toFixed(0)}% &rarr; {(btcRec.new_held_exposure * 100).toFixed(0)}%</span></div><div><strong>{btcRec.order_qty > 0 ? `${btcRec.order_qty.toFixed(4)} BTC` : 'none'}</strong><span>{btcRec.limit_price ? `limit ${money(btcRec.limit_price)} · ${money(btcRec.order_notional)}` : 'no order'}</span></div><div><strong>{money(btcRec.sleeve_usd)}</strong><span>target {btcRec.target_qty.toFixed(4)} BTC</span></div><div><strong>{btcRun?.execution?.status ?? '---'}</strong><span>{btcRun?.execution?.reason}</span></div><div><span className="wheel-pill">{btcRun?.mode === 'live_automated' ? 'LIVE AUTO' : btcRun?.mode === 'paper_automated' ? 'PAPER AUTO' : 'RESEARCH'}</span></div></div> : <div className="empty">No rebalance decision yet &mdash; needs an IBKR connection.</div>}
        {!!btcRec?.reasons.length && <details className="score-math"><summary>Rule reasoning</summary><div>{btcRec.reasons.map((reason, index) => <p key={index}>{reason}</p>)}</div></details>}</section>
      <section className="panel calc-panel"><div className="panel-header"><div><p className="eyebrow">STRATEGY POSITION</p><h2>Strategy-owned BTC</h2></div><span className="last-refresh">BTC held outside this strategy is never sold</span></div><div className="order-detail-grid"><div><span>BTC QUANTITY</span><strong>{btcPosition ? btcPosition.btc_qty.toFixed(4) : '---'}</strong></div><div><span>AVERAGE COST</span><strong>{btcPosition?.btc_qty ? money(btcPosition.avg_cost) : '---'}</strong></div><div><span>UNREALIZED P&amp;L (AT LAST MARK)</span><strong className={btcUnrealized == null ? '' : btcUnrealized >= 0 ? 'positive' : 'negative'}>{money(btcUnrealized)}</strong></div><div><span>REALIZED P&amp;L (ALL TIME)</span><strong className={(btcPosition?.realized_pnl ?? 0) >= 0 ? 'positive' : 'negative'}>{money(btcPosition?.realized_pnl)}</strong></div><div><span>TRAILING STOP (PEAK CLOSE - 4x ATR)</span><strong className={btcRec?.stop_triggered ? 'negative' : ''}>{btcRec?.stop_price ? `${money(btcRec.stop_price)}${btcMark ? ` (${((btcRec.stop_price / btcMark - 1) * 100).toFixed(1)}%)` : ''}` : btcRec?.stop_price_if_filled ? `${money(btcRec.stop_price_if_filled)} if the recommended order fills` : 'no position'}</strong></div><div><span>RE-ENTRY</span><strong className={btcPosition?.stop_locked ? 'negative' : ''}>{btcPosition?.stop_locked ? `Locked until close > ${money(btcSignal?.reentry_breakout_level)}` : 'Open to signal'}</strong></div><div><span>PROFIT TRIM (1/3 AT +50% VS ENTRY)</span><strong className={btcPosition?.profit_taken ? 'positive' : ''}>{btcPosition?.profit_taken ? 'Taken this trade' : btcPosition?.entry_price ? `Pending at a close of ${money(btcPosition.entry_price * 1.5)}` : 'no position'}</strong></div><div><span>RISK AT STOP</span><strong>{btcRec?.risk_at_stop_usd ? `${money(btcRec.risk_at_stop_usd)} (${(btcRec.risk_at_stop_pct_of_net_liq * 100).toFixed(2)}% of net liq)` : '---'}</strong></div></div>
        {!!btc?.recent_fills.length && <div className="btc-table"><div className="btc-fill-head"><span>TIME</span><span>SIDE</span><span>QTY</span><span>PRICE</span><span>REALIZED</span></div>{[...btc.recent_fills].reverse().map((fill, index) => <div className="btc-fill-row" key={index}><span>{dateTime(fill.timestamp)}</span><strong className={fill.action === 'BUY' ? 'positive' : 'negative'}>{fill.action}</strong><span>{fill.qty.toFixed(4)}</span><span>{money(fill.price)}</span><span className={fill.realized_pnl >= 0 ? 'positive' : 'negative'}>{money(fill.realized_pnl)}</span></div>)}</div>}</section>
      <section className="panel calc-panel"><div className="panel-header"><div><p className="eyebrow">HISTORICAL RESEARCH</p><h2>Backtest vs buy and hold</h2></div>{btc?.backtest && <span className="last-refresh">{btc.backtest.data.first_bar} to {btc.backtest.data.last_bar} &middot; {(btc.backtest.assumptions.cost_per_side * 100).toFixed(2)}%/side costs &middot; next-bar execution</span>}</div>{btc?.backtest ? <><BtcBacktestTable backtest={btc.backtest} /><BtcYearlyChart backtest={btc.backtest} /></> : <div className="empty">No backtest report &mdash; run python -m btctrend.backtest.</div>}</section></>}
    {selectedWheel && <div className="drawer-backdrop" role="presentation" onMouseDown={() => setSelectedWheel(null)}><aside className="news-drawer wheel-detail-drawer" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><header className="drawer-header"><div><p className="eyebrow">WHEEL DETAIL</p><h2>{selectedWheel.symbol} strategy state</h2><span>Latest automated {wheel?.connection_mode ?? 'paper'} run and position ownership</span></div><button className="icon-button" onClick={() => setSelectedWheel(null)}><X size={18} /></button></header><div className="wheel-detail-body"><div className="order-detail-grid"><div><span>WHEEL SHARES</span><strong>{selectedWheel.active_wheel_shares}</strong></div><div><span>EXTERNAL SHARES</span><strong>{selectedWheel.external_shares}</strong></div><div><span>POOLED SHARES</span><strong>{selectedWheel.stock_pool.shares}</strong></div><div><span>POOL AVG COST</span><strong>{money(selectedWheel.stock_pool.average_cost)}</strong></div></div><div className="order-detail-note"><p className="eyebrow">LATEST AUTOMATED RUN</p><strong>{wheel?.latest_runs?.[selectedWheel.symbol]?.status === 'data_unavailable' ? 'No active put because IBKR option-chain data was unavailable.' : wheel?.latest_runs?.[selectedWheel.symbol]?.recommendation?.action ?? 'No latest wheel recommendation'}</strong><span>{wheel?.latest_runs?.[selectedWheel.symbol]?.reason ?? wheel?.latest_runs?.[selectedWheel.symbol]?.execution?.reason ?? ''}</span></div><div className="order-detail-note"><p className="eyebrow">PARAMETERS</p><strong>Put: 21-45 DTE, ~5% OTM, |delta| 0.15-0.30, 8% annualized yield, 10% collateral cap.</strong><span>Call: only after a registered put assignment creates at least 100 active wheel shares.</span></div></div></aside></div>}
    {selectedSignal && <div className="drawer-backdrop" role="presentation" onMouseDown={() => setSelectedSignal(null)}><aside className="news-drawer contribution-drawer" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><header className="drawer-header"><div><p className="eyebrow">SIGNAL CONTRIBUTIONS</p><h2>{selectedSignal} news evidence</h2><span>Top {Math.min(shown, signalArticles.length)} of {signalArticles.length} contributions from the latest audit run</span></div><button className="icon-button" onClick={() => setSelectedSignal(null)}><X size={18} /></button></header><div className="drawer-articles">{signalArticles.slice(0, shown).map((article, index) => <article className="audit-article" key={`${article.article_id}-${index}`}><div className="article-top"><div><span className={`article-sentiment ${article.sentiment}`}>{article.sentiment}</span><strong>{article.title}</strong></div>{article.url && <a href={article.url} target="_blank" rel="noreferrer"><ExternalLink size={16} /></a>}</div><p>{article.summary}</p><div className="article-meta"><span>{article.source}</span><span>{article.topic}</span><span>contribution {article.sentiment_contribution?.toFixed(4) ?? '---'}</span></div><ScoreMath article={article} /></article>)}{signalArticles.length > shown && <button className="show-more" onClick={() => setShown((count) => count + 10)}>Show 10 more contributions</button>}{!signalArticles.length && <div className="empty">No contribution data is available for this symbol in the latest audit run.</div>}</div></aside></div>}
    {selectedOrder && <div className="drawer-backdrop" role="presentation" onMouseDown={() => setSelectedOrder(null)}><aside className="news-drawer order-drawer" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><header className="drawer-header"><div><p className="eyebrow">ORDER DETAIL</p><h2>{selectedOrder.symbol} {selectedOrder.status}</h2><span>{dateTime(selectedOrder.timestamp)} · {selectedOrder.broker.toUpperCase()}</span></div><button className="icon-button" onClick={() => setSelectedOrder(null)}><X size={18} /></button></header><div className="order-detail-grid"><div><span>ACTION</span><strong>{selectedOrder.action ?? 'ORDER'}</strong></div><div><span>QUANTITY</span><strong>{selectedOrder.requested_qty} shares</strong></div><div><span>ENTRY LIMIT</span><strong>{money(selectedOrder.bracket.entry_limit ?? selectedOrder.price)}</strong></div><div><span>FILLED</span><strong>{selectedOrder.filled_qty} shares</strong></div><div><span>TAKE PROFIT</span><strong>{money(selectedOrder.bracket.take_profit)}</strong></div><div><span>STOP LOSS</span><strong>{money(selectedOrder.bracket.stop_loss)}</strong></div></div><div className="order-detail-note"><p className="eyebrow">STATUS REASON</p><strong>{selectedOrder.reasons[0] ?? (selectedOrder.status === 'PENDING' ? 'Waiting for IBKR paper execution' : 'No additional broker reason recorded')}</strong></div></aside></div>}
    {isMobile && <nav className="mobile-nav"><button className={view === 'EQUITY' ? 'active' : ''} onClick={() => setView('EQUITY')}><Radio size={20} /><span>Signals</span></button><button className={view === 'WHEEL' ? 'active' : ''} onClick={() => setView('WHEEL')}><BadgeDollarSign size={20} /><span>Wheel</span></button><button className={view === 'GOLD' ? 'active' : ''} onClick={() => setView('GOLD')}><BadgeDollarSign size={20} /><span>Gold</span></button><button className={view === 'BULLSPREAD' ? 'active' : ''} onClick={() => setView('BULLSPREAD')}><BadgeDollarSign size={20} /><span>MS Spread</span></button><button className={view === 'BTC' ? 'active' : ''} onClick={() => setView('BTC')}><ArrowUpRight size={20} /><span>BTC</span></button></nav>}
  </main>
}
