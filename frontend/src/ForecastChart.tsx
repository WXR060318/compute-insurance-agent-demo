import { useEffect, useId, useState } from 'react';
import type { Evaluation } from './types';
import { num, timeOf } from './api';
import Icon from './Icons';
export default function ForecastChart({ evaluation: e }: { evaluation: Evaluation }) {
 const gid = useId().replace(/:/g, '');
 const [hover, setHover] = useState<number | null>(null);
 const points = e.chart;
 const [smallScreen, setSmallScreen] = useState(() => window.matchMedia('(max-width: 540px)').matches);
 useEffect(() => { const media = window.matchMedia('(max-width: 540px)'); const update = () => setSmallScreen(media.matches); media.addEventListener('change', update); return () => media.removeEventListener('change', update); }, []);
 const width = smallScreen ? 560 : 1000, height = 326, left = 47, right = 22, top = 35, bottom = 38;
 const low = points[0]?.minute ?? e.input.minute - 60;
 const high = points[points.length - 1]?.minute ?? e.input.minute + 180;
 const values = points.flatMap(p => [p.demand, p.forecast, p.capacity]).filter((v): v is number => v != null && Number.isFinite(v));
 const maximum = Math.max(4, Math.ceil(Math.max(...values, 0) * 1.25 / 4) * 4);
 const x = (v: number) => left + (v - low) / Math.max(1, high - low) * (width - left - right);
 const y = (v: number) => height - bottom - v / maximum * (height - top - bottom);
 const build = (field: 'demand' | 'forecast' | 'capacity') => {
   let isOpen = false;
   return points.map(p => { const v = p[field]; if (v == null || !Number.isFinite(v)) { isOpen = false; return ''; } const prefix = isOpen ? 'L' : 'M'; isOpen = true; return prefix + x(p.minute).toFixed(1) + ',' + y(v).toFixed(1); }).join(' ');
 };
 const area = (field: 'demand' | 'forecast') => {
   const valid = points.filter(p => p[field] != null && Number.isFinite(p[field]));
   if (!valid.length) return '';
   return build(field) + ' L' + x(valid[valid.length - 1].minute) + ',' + (height - bottom) + ' L' + x(valid[0].minute) + ',' + (height - bottom) + ' Z';
 };
 const nowX = x(e.input.minute);
 const tickIndices = [0, Math.round((points.length - 1) / 4), Math.round((points.length - 1) / 2), Math.round((points.length - 1) * 3 / 4), points.length - 1];
 const hoverPoint = hover == null ? null : points[hover];
 const isStale = e.risk.level === 'unknown';
 return <section className="panel forecast-panel">
   <div className="panel-header chart-header"><div><h2>算力需求与容量</h2><p>近期观测与已知计划任务 · {e.company.gpu_model}</p></div><div className="chart-legend"><span><i className="legend-solid"/>历史需求</span><span><i className="legend-dash"/>需求预测</span><span><i className="legend-cap"/>可用容量</span></div></div>
   <div className="chart-wrap" onMouseLeave={() => setHover(null)}>
    <svg className="forecast-svg" viewBox={'0 0 ' + width + ' ' + height} role="img" aria-label={'算力需求预测曲线，未来峰值缺口' + num(e.metrics.peak_gap) + '张GPU'} onMouseMove={event => { const rect = event.currentTarget.getBoundingClientRect(); const mx = (event.clientX - rect.left) / rect.width * width; const minute = low + (mx - left) / (width - left - right) * (high - low); let nearest = 0; points.forEach((p, i) => { if (Math.abs(p.minute - minute) < Math.abs(points[nearest].minute - minute)) nearest = i; }); setHover(nearest); }}>
     <defs><linearGradient id={gid + 'history'} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#219b85" stopOpacity=".15"/><stop offset="100%" stopColor="#219b85" stopOpacity=".015"/></linearGradient><linearGradient id={gid + 'future'} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#d59e44" stopOpacity=".16"/><stop offset="100%" stopColor="#d59e44" stopOpacity=".025"/></linearGradient></defs>
     <rect x={Math.max(left, nowX)} y={top} width={Math.max(0, width - right - nowX)} height={height - top - bottom} fill="#fcfbf6"/>
     {[0, 1, 2, 3, 4].map(n => <g key={n}><line x1={left} x2={width - right} y1={y(maximum / 4 * n)} y2={y(maximum / 4 * n)} stroke="#e9ece8" strokeDasharray="3 5"/><text x={left - 14} y={y(maximum / 4 * n) + 4} textAnchor="end" className="chart-label">{num(maximum / 4 * n)}</text></g>)}
     <text x={left - 16} y={17} textAnchor="end" className="chart-label">张</text>
     <text x={left + 10} y={top + 17} className="chart-zone-label">历史观测</text><text x={Math.min(nowX + 18, width - 90)} y={top + 17} className="chart-zone-label">预测区间</text>
     <path d={area('demand')} fill={'url(#' + gid + 'history)'} stroke="none"/><path d={area('forecast')} fill={'url(#' + gid + 'future)'} stroke="none"/>
     <path d={build('capacity')} fill="none" stroke="#88969e" strokeWidth="1.6" strokeDasharray="7 5"/>
     <path d={build('demand')} fill="none" stroke="#208e7c" strokeWidth="3.1" strokeLinejoin="round"/>
     <path d={build('forecast')} fill="none" stroke="#cc9848" strokeWidth="3.1" strokeDasharray="7 5" strokeLinejoin="round"/>
     <line x1={nowX} x2={nowX} y1={top - 5} y2={height - bottom + 2} stroke="#253f50" strokeWidth="1.3" strokeDasharray="3 5"/>
     <rect x={nowX - 45} y={8} width={90} height={23} rx={5} fill="#183548"/><text x={nowX} y={24} textAnchor="middle" fill="white" className="chart-now-label">当前 {timeOf(e.now)}</text>
     {tickIndices.map((index, i) => points[index] ? <text key={i} x={x(points[index].minute)} y={height - 13} textAnchor={i === 0 ? 'start' : i === 4 ? 'end' : 'middle'} className="chart-label">{points[index].time}</text> : null)}
     {hoverPoint && <g><line x1={x(hoverPoint.minute)} x2={x(hoverPoint.minute)} y1={top} y2={height - bottom} stroke="#bcc5c5"/>{(['demand', 'forecast'] as const).map(field => hoverPoint[field] != null ? <circle key={field} cx={x(hoverPoint.minute)} cy={y(hoverPoint[field]!)} r="5" fill={field === 'demand' ? '#208e7c' : '#cc9848'} stroke="white" strokeWidth="2"/> : null)}</g>}
    </svg>
    {hoverPoint && <div className="chart-tooltip" style={{ left: Math.max(5, Math.min(75, x(hoverPoint.minute) / width * 100)) + '%' }}><strong>{hoverPoint.time}</strong><span>历史需求 <b>{num(hoverPoint.demand)} 张</b></span><span>预测需求 <b>{num(hoverPoint.forecast)} 张</b></span><span>可用容量 <b>{num(hoverPoint.capacity)} 张</b></span></div>}
   </div>
   {isStale ? <div className="chart-note warning"><Icon name="alert" size={17}/><span>数据已失效，未来预测已暂停。最后有效数据 {timeOf(e.meta.data_time)}。</span></div> : <div className="chart-note"><Icon name="info" size={16}/><span>预测依据：{e.meta.forecast_method}。虚线为预测值，非未来实际观测。</span></div>}
   <div className="chart-summary"><div><span className="summary-icon"><Icon name="clock" size={18}/></span><span>首次预计短缺<strong>{e.metrics.first_shortage_at || (isStale ? '无法评估' : '无短缺')}</strong></span></div><div><span className="summary-icon amber"><Icon name="cpu" size={18}/></span><span>未来峰值需求<strong>{num(e.metrics.predicted_peak)} <small>张 GPU</small></strong></span></div><div><span className="summary-icon blue"><Icon name="activity" size={18}/></span><span>预计短缺时长<strong>{num(e.metrics.shortage_duration_minutes)} <small>分钟</small></strong></span></div></div>
 </section>;
}
