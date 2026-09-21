import 'package:flutter_test/flutter_test.dart';

import 'package:dispenser_ui/main.dart';

void main() {
  testWidgets('Tela inicial exibe aguardando dose', (WidgetTester tester) async {
    await tester.pumpWidget(const DispenserUi());

    expect(find.text('Aguardando a próxima dose'), findsOneWidget);
    expect(find.text('Dispensador de medicamentos'), findsOneWidget);
  });
}