// Licensed to the Apache Software Foundation (ASF) under one or more
// contributor license agreements. See the NOTICE file distributed with
// this work for additional information regarding copyright ownership.
// The ASF licenses this file to You under the Apache License, Version 2.0
// (the "License"); you may not use this file except in compliance with
// the License. You may obtain a copy of the License at
// http://www.apache.org/licenses/LICENSE-2.0
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"time"

	"github.com/google/uuid"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

type request struct {
	SchemaVersion int    `json:"schema_version"`
	ExecutionID   string `json:"execution_id"`
	Endpoint      string `json:"endpoint"`
	AccessKey     string `json:"access_key"`
	SecretKey     string `json:"secret_key"`
	TLS           bool   `json:"tls"`
}

type result struct {
	SchemaVersion int    `json:"schema_version"`
	ExecutionID   string `json:"execution_id"`
	Outcome       string `json:"outcome"`
	Stage         string `json:"stage"`
	Bucket        string `json:"bucket"`
	Object        string `json:"object"`
	SHA256        string `json:"sha256"`
	Cleanup       bool   `json:"cleanup"`
}

func check(input request) (observed result) {
	observed = result{SchemaVersion: 1, ExecutionID: input.ExecutionID, Outcome: "UNRESOLVED", Stage: "client"}
	client, err := minio.New(input.Endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(input.AccessKey, input.SecretKey, ""),
		Secure: input.TLS,
	})
	if err != nil {
		return observed
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	unique := make([]byte, 16)
	if _, err := rand.Read(unique); err != nil {
		return observed
	}
	observed.Bucket = "ambari-mpack-" + hex.EncodeToString(unique)
	observed.Object = "probe"
	observed.Stage = "create"
	if err := client.MakeBucket(ctx, observed.Bucket, minio.MakeBucketOptions{}); err != nil {
		return observed
	}
	defer func() {
		removeObject := client.RemoveObject(ctx, observed.Bucket, observed.Object, minio.RemoveObjectOptions{})
		removeBucket := client.RemoveBucket(ctx, observed.Bucket)
		observed.Cleanup = removeObject == nil && removeBucket == nil
		if !observed.Cleanup {
			observed.Outcome = "UNRESOLVED"
			observed.Stage = "cleanup"
		}
	}()
	payload := []byte("ambari-mpack:" + input.ExecutionID + ":" + hex.EncodeToString(unique))
	digest := sha256.Sum256(payload)
	observed.SHA256 = hex.EncodeToString(digest[:])
	observed.Stage = "write"
	if _, err := client.PutObject(ctx, observed.Bucket, observed.Object, bytes.NewReader(payload),
		int64(len(payload)), minio.PutObjectOptions{}); err != nil {
		return observed
	}
	observed.Stage = "read"
	object, err := client.GetObject(ctx, observed.Bucket, observed.Object, minio.GetObjectOptions{})
	if err != nil {
		return observed
	}
	defer object.Close()
	got, err := io.ReadAll(io.LimitReader(object, 1024))
	if err != nil || !bytes.Equal(got, payload) {
		return observed
	}
	observed.Outcome = "APPLIED"
	observed.Stage = "verified"
	return observed
}

func main() {
	if len(os.Args) != 3 {
		os.Exit(2)
	}
	file, err := os.Open(os.Args[1])
	if err != nil {
		os.Exit(2)
	}
	defer file.Close()
	decoder := json.NewDecoder(io.LimitReader(file, 16384))
	decoder.DisallowUnknownFields()
	var input request
	if decoder.Decode(&input) != nil || input.SchemaVersion != 1 || input.Endpoint == "" ||
		input.AccessKey == "" || input.SecretKey == "" {
		os.Exit(2)
	}
	parsed, err := uuid.Parse(input.ExecutionID)
	if err != nil || parsed.String() != input.ExecutionID {
		os.Exit(2)
	}
	observed := check(input)
	output, err := os.OpenFile(os.Args[2], os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		os.Exit(2)
	}
	if json.NewEncoder(output).Encode(observed) != nil || output.Close() != nil {
		os.Exit(2)
	}
	if observed.Outcome != "APPLIED" {
		os.Exit(1)
	}
}
