function SegmentedControl({ label, help, options, value, onChange, getLabel = (o) => o.label, getKey = (o) => o.label }) {
  return (
    <div className="mb-6">
      <div className="font-mono text-xs uppercase tracking-widest border-b-2 border-black pb-1 mb-2">{label}</div>
      {help && <p className="font-mono text-[11px] text-zinc-500 mb-2">{help}</p>}
      <div className="flex border-2 border-black items-stretch">
        {options.map((opt) => {
          const key = getKey(opt);
          const selected = getKey(value) === key;
          return (
            <button
              key={key}
              onClick={() => onChange(opt)}
              className={"flex-1 px-2 py-2 font-mono text-xs uppercase text-center leading-tight border-r-2 border-black last:border-r-0 " +
                (selected ? "bg-black text-white" : "bg-white hover:bg-zinc-100")}
            >
              {getLabel(opt)}
            </button>
          );
        })}
      </div>
    </div>
  );
}
function NumberDial({ label, help, options, value, onChange, suffix = "" }) {
  const displayValue = typeof value === "object" ? value.label : value;
  return (
    <div className="mb-6">
      <div className="flex items-baseline justify-between border-b-2 border-black pb-1 mb-2">
        <span className="font-mono text-xs uppercase tracking-widest">{label}</span>
        <span className="font-mono text-xs">{displayValue}{suffix}</span>
      </div>
      {help && <p className="font-mono text-[11px] text-zinc-500 mb-2">{help}</p>}
      <input
        type="range"
        min={0}
        max={options.length - 1}
        step={1}
        value={options.indexOf(value)}
        onChange={(e) => onChange(options[Number(e.target.value)])}
        className="w-full accent-black"
      />
    </div>
  );
}

function SummaryTable({ rows }) {
  return (
    <table className="w-full text-xs mb-6">
      <tbody>
        {rows.map(([label, val]) => (
          <tr key={label} className="border-b border-zinc-300">
            <td className="py-1.5 text-zinc-500">{label}</td>
            <td className="py-1.5 text-right">{val}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}