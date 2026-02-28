// Codebot Air — Firmware v1 (Variant A pin test)
// Motor driver: L298N dual H-bridge
// Board: Arduino UNO (ATmega328P, CH340)
//
// Serial commands (9600 baud):
//   F = forward    B = backward
//   L = turn left  R = turn right
//   S = stop
//   + = speed up   - = speed down
//   ? = ping (replies "CODEBOT_OK")

// --- Pin definitions (Variant A) ---
const int ENA = 6;   // Left motor speed  (PWM)
const int IN1 = 7;   // Left motor fwd
const int IN2 = 5;   // Left motor bwd
const int ENB = 3;   // Right motor speed (PWM)
const int IN3 = 4;   // Right motor fwd
const int IN4 = 2;   // Right motor bwd

// --- Default speed (0-255) ---
int motorSpeed = 180;

// ------------------------------------
void setup() {
  Serial.begin(9600);
  pinMode(ENA, OUTPUT); pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT);
  pinMode(ENB, OUTPUT); pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT);
  stopMotors();
  Serial.println("CODEBOT_READY");
}

void loop() {
  if (Serial.available() > 0) {
    char cmd = (char)Serial.read();
    switch (cmd) {
      case 'F': case 'f': forward();   Serial.println("FORWARD");   break;
      case 'B': case 'b': backward();  Serial.println("BACKWARD");  break;
      case 'L': case 'l': turnLeft();  Serial.println("LEFT");      break;
      case 'R': case 'r': turnRight(); Serial.println("RIGHT");     break;
      case 'S': case 's': stopMotors();Serial.println("STOP");      break;
      case '+':
        motorSpeed = min(motorSpeed + 20, 255);
        Serial.print("SPEED:"); Serial.println(motorSpeed); break;
      case '-':
        motorSpeed = max(motorSpeed - 20, 60);
        Serial.print("SPEED:"); Serial.println(motorSpeed); break;
      case '?':
        Serial.println("CODEBOT_OK"); break;
      default: break;
    }
  }
}

// ------------------------------------
void forward() {
  analogWrite(ENA, motorSpeed); analogWrite(ENB, motorSpeed);
  digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
  digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);
}

void backward() {
  analogWrite(ENA, motorSpeed); analogWrite(ENB, motorSpeed);
  digitalWrite(IN1, LOW);  digitalWrite(IN2, HIGH);
  digitalWrite(IN3, LOW);  digitalWrite(IN4, HIGH);
}

void turnLeft() {
  analogWrite(ENA, motorSpeed); analogWrite(ENB, motorSpeed);
  digitalWrite(IN1, LOW);  digitalWrite(IN2, HIGH);  // left motor bwd
  digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);   // right motor fwd
}

void turnRight() {
  analogWrite(ENA, motorSpeed); analogWrite(ENB, motorSpeed);
  digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);   // left motor fwd
  digitalWrite(IN3, LOW);  digitalWrite(IN4, HIGH);  // right motor bwd
}

void stopMotors() {
  analogWrite(ENA, 0); analogWrite(ENB, 0);
  digitalWrite(IN1, LOW); digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW); digitalWrite(IN4, LOW);
}
