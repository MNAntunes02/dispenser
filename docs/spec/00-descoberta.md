# Fase 0: Descoberta

Objetivo: entender o app Flutter, o Pi e a placa ANTES de projetar. Não escreva código do sistema nesta fase.
Saída: `dispenser/docs/DESCOBERTA.md`. Ao final, liste as perguntas em aberto e PARE.

## 1. App Flutter (somente leitura)
Procure em `lib/`, `pubspec.yaml`, `android/`, `ios/` e arquivos de configuração. Registre com caminhos de arquivo:
- **Backend**: Firebase/Firestore, REST, Supabase ou outro? Pacotes usados (`pubspec.yaml`), URLs base, coleções/tabelas.
- **Autenticação**: como o app autentica e como um dispositivo sem usuário humano poderia autenticar (conta de serviço, token, login dedicado). Não copie segredos para o repositório.
- **Modelos**: medicamento, dose, horário, recorrência, dosagem, paciente, cuidador, histórico de adesão (campos e tipos).
- **Agendamento**: dias da semana, intervalos, "se necessário", fuso horário, janela de tolerância, doses múltiplas no mesmo horário.
- **Registro de adesão**: como o app marca dose tomada/perdida/pulada.
- **Slots**: existe conceito de gaveta/compartimento/slot? Como relaciona com medicamento?
- **Notificações**: FCM, local, e-mail ou SMS; como o cuidador é modelado e avisado.
- **Hardware**: existe código de integração com dispositivo (Bluetooth, MQTT, serial)?
- **Regras de negócio** que o dispensador deve replicar de forma idêntica.

## 2. Ambiente do Raspberry
Pergunte se você está rodando no Pi ou em outra máquina. Se no Pi, execute; senão, peça a saída ao usuário:
```
lsb_release -a; uname -m; free -h; df -h /
timedatectl; ls /dev/serial/by-id /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
i2cdetect -y 1 2>/dev/null; aplay -l 2>/dev/null
```
Registre: versão do Ubuntu, arquitetura, RAM, ambiente gráfico presente ou não, modelo e interface da tela LCD (HDMI/DSI/SPI/I2C, touch ou não), como áudio, LEDs e botões estão ligados.

## 3. Placa controladora
- Existe firmware pronto? Onde está? Se sim, documente o protocolo real (comandos, eventos, baud rate, formato).
- Se não existe, apenas registre a lacuna; a proposta de protocolo vem na Fase 1.

## 4. Formato de DESCOBERTA.md
Seções: Resumo, App (achados por tema acima), Ambiente do Pi, Placa, Riscos, Perguntas em aberto (numeradas, cada uma com sua sugestão de resposta padrão).
