interface NoteEditorProps {
  value: string
  disabled: boolean
  onChange: (value: string) => void
}

export function NoteEditor({ value, disabled, onChange }: NoteEditorProps) {
  return (
    <div>
      <label className="field-label" htmlFor="observation-note">
        观察笔记
      </label>
      <textarea
        disabled={disabled}
        id="observation-note"
        onChange={(event) => onChange(event.target.value)}
        placeholder="例如：傍晚在葛西临海公园，看到十几只家燕贴着水面飞……"
        rows={9}
        value={value}
      />
    </div>
  )
}
