/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements. See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License. You may obtain a copy of the License at
 * http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.Base64;
import java.util.Properties;
import java.util.UUID;
import org.apache.kyuubi.jdbc.hive.KyuubiConnection;
import org.apache.kyuubi.jdbc.hive.KyuubiStatement;

/** Emits a bounded, execution-associated JDBC observation, independently of diagnostic output. */
public class KyuubiSqlCheck {
  private static String string(String value) {
    if (value == null) {
      throw new IllegalArgumentException("A required JDBC observation is missing");
    }
    StringBuilder result = new StringBuilder("\"");
    for (char character : value.toCharArray()) {
      if (character == '"' || character == '\\') {
        result.append('\\').append(character);
      } else if (character < 32) {
        result.append(String.format("\\u%04x", (int) character));
      } else {
        result.append(character);
      }
    }
    return result.append('"').toString();
  }

  private static String operationId(KyuubiStatement statement) {
    byte[] bytes = Base64.getUrlDecoder().decode(statement.getYarnATSGuid());
    if (bytes.length != 16) {
      throw new IllegalStateException("Invalid server operation GUID");
    }
    ByteBuffer buffer = ByteBuffer.wrap(bytes);
    return new UUID(buffer.getLong(), buffer.getLong()).toString();
  }

  public static void main(String[] arguments) throws Exception {
    if (arguments.length != 6) {
      throw new IllegalArgumentException("Expected endpoint and execution identity arguments");
    }
    String execution = UUID.fromString(arguments[3]).toString();
    String task = arguments[4].equals("null") ? "null" : Long.toString(Long.parseLong(arguments[4]));
    String prefix = "{\"schema_version\":1,\"definition_snapshot\":" + string(arguments[2])
        + ",\"execution_id\":" + string(execution) + ",\"task_id\":" + task
        + ",\"action\":\"sql\"";
    Path destination = Path.of(arguments[5]);
    String output;
    boolean success = false;
    try {
      Class.forName("org.apache.kyuubi.jdbc.KyuubiHiveDriver");
      Properties properties = new Properties();
      properties.setProperty("user", "kyuubi");
      DriverManager.setLoginTimeout(180);
      String session;
      String operation;
      String engine;
      String driverVersion;
      long total;
      long count;
      String echoed;
      String url = "jdbc:kyuubi://" + arguments[0] + ":" + Integer.parseInt(arguments[1]) + "/default";
      try (Connection connection = DriverManager.getConnection(url, properties)) {
        if (!(connection instanceof KyuubiConnection)) {
          throw new IllegalStateException("Unexpected JDBC driver");
        }
        driverVersion = connection.getMetaData().getDriverVersion();
        try (Statement statement = connection.createStatement()) {
          statement.setQueryTimeout(120);
          try (ResultSet result = statement.executeQuery("DESCRIBE SESSION")) {
            if (!result.next()) {
              throw new IllegalStateException("Missing session identity");
            }
            session = UUID.fromString(result.getString("SESSION_ID")).toString();
            if (!"kyuubi".equals(result.getString("SESSION_USER")) || result.next()) {
              throw new IllegalStateException("Foreign or ambiguous session");
            }
          }
        }
        try (KyuubiStatement statement = (KyuubiStatement) connection.createStatement()) {
          statement.setQueryTimeout(180);
          try (ResultSet result = statement.executeQuery(
              "SELECT sum(id) AS total, count(*) AS rows, '" + execution
                  + "' AS execution_id FROM range(10)")) {
            operation = operationId(statement);
            if (!result.next()) {
              throw new IllegalStateException("Missing SQL result");
            }
            total = result.getLong("total");
            if (result.wasNull()) {
              throw new IllegalStateException("Missing aggregate");
            }
            count = result.getLong("rows");
            if (result.wasNull()) {
              throw new IllegalStateException("Missing row count");
            }
            echoed = result.getString("execution_id");
            if (total != 45 || count != 10 || !execution.equals(echoed) || result.next()) {
              throw new IllegalStateException("SQL result does not match this execution");
            }
            engine = ((KyuubiConnection) connection).getEngineId();
            if (engine == null || engine.isEmpty()) {
              throw new IllegalStateException("Missing engine identity");
            }
          }
        }
      }
      output = prefix + ",\"outcome\":\"APPLIED\",\"observations\":{"
          + "\"session_id\":" + string(session) + ",\"operation_id\":" + string(operation)
          + ",\"engine_id\":" + string(engine) + ",\"driver_version\":" + string(driverVersion)
          + ",\"sum\":" + total + ",\"rows\":" + count
          + ",\"execution_id\":" + string(echoed) + ",\"resources_closed\":true}}";
      success = true;
    } catch (Exception failure) {
      output = prefix + ",\"outcome\":\"UNRESOLVED\",\"observations\":{\"error_type\":"
          + string(failure.getClass().getName()) + "}}";
    }
    Path temporary = Files.createTempFile(destination.getParent(), ".jdbc-", ".json");
    Files.writeString(temporary, output, StandardCharsets.UTF_8);
    Files.move(temporary, destination, StandardCopyOption.ATOMIC_MOVE);
    if (!success) {
      System.exit(1);
    }
  }
}
