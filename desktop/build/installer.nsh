!macro customInstall
  DetailPrint "Configurando NotasFlow..."
!macroend

!macro customUnInstall
  DetailPrint "Removendo NotasFlow..."
  ; Não remover dados do usuário por padrão (preservar banco)
  ; RMDir /r "$APPDATA\NotasFlow"
!macroend
