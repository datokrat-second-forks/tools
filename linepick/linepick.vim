" linepick.vim — rewrite the current line via the linepick tool.
"
" Usage: source this file from your .vimrc, e.g.
"     source /path/to/linepick.vim
" Then press <Leader>f in normal mode. The current line and cursor column are
" handed to the linepick tool as JSON; its JSON reply replaces the line and
" repositions the cursor.
"
" By default the tool is the 'linepick' script sitting next to this file.
" Override with g:linepick_command (also handy for tests).
"
" The 'cpo' guard below resets 'cpoptions' to Vim defaults while sourcing, so
" the <Leader>/<Plug>/<silent> mappings are interpreted even when this file is
" sourced in 'compatible' mode (e.g. from a --cmd before the vimrc); it is
" restored at the end.

let s:save_cpo = &cpo
set cpo&vim

if !exists('g:linepick_command')
  let g:linepick_command = expand('<sfile>:p:h') . '/linepick'
endif

function! LinePick() abort
  " ':!' hands the terminal to the tool (so it can run fzf). The JSON travels
  " through temp files passed as arguments — not stdin/stdout — so the tool's
  " terminal stays free and nothing collides with what it draws on screen.
  let l:infile = tempname()
  let l:outfile = tempname()
  call writefile([json_encode({'line': getline('.'), 'col': col('.')})], l:infile)
  let l:cmd = g:linepick_command . ' ' . fnameescape(l:infile) . ' ' . fnameescape(l:outfile)
  if get(g:, 'linepick_debug', 0)
    echom 'linepick exec: ' . l:cmd
  endif
  execute 'silent !' . l:cmd
  redraw!
  let l:raw = filereadable(l:outfile) ? join(readfile(l:outfile), "\n") : ''
  if v:shell_error != 0
    echohl WarningMsg | echom 'linepick: command exited ' . v:shell_error . ': ' . g:linepick_command | echohl None
  elseif empty(l:raw)
    echohl WarningMsg | echom 'linepick: no output from: ' . g:linepick_command | echohl None
  else
    let l:res = json_decode(l:raw)
    call setline('.', l:res.line)
    call cursor(line('.'), l:res.col)
  endif
  call delete(l:infile)
  call delete(l:outfile)
endfunction

command! LinePick call LinePick()

" Bind your own key to <Plug>(LinePick), e.g. in your vimrc:
"     nmap <silent> <Leader>f <Plug>(LinePick)
" As a convenience we also create that default mapping, but only when <Leader>f
" is still free. Note <Leader> resolves to your 'mapleader' as it stands when
" this file is sourced (default '\'), so source this after setting mapleader.
nnoremap <silent> <Plug>(LinePick) :call LinePick()<CR>
if empty(maparg('<Leader>f', 'n'))
  nmap <silent> <Leader>f <Plug>(LinePick)
endif

let &cpo = s:save_cpo
unlet s:save_cpo
