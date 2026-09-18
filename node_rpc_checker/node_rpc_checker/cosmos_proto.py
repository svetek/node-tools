"""Wire-compatible projections of the Cosmos SDK v0.50 Tendermint API.

Only fields consumed by the checker are declared; protobuf skips other fields.
Field numbers follow cosmos/base/tendermint/v1beta1/{query,types}.proto and
CometBFT v0.38 tendermint/p2p/types.proto. No reflection service is required.
"""

from google.protobuf import (  # type: ignore[import-untyped]
    descriptor_pb2,
    descriptor_pool,
    message_factory,
)
from google.protobuf.json_format import MessageToDict  # type: ignore[import-untyped]


def message_types():
    file = descriptor_pb2.FileDescriptorProto(
        name="checker_cosmos.proto", package="checker", syntax="proto3"
    )
    # name, field number, scalar type or nested message name
    definitions = {
        "Empty": [],
        "HeightRequest": [("height", 1, "int64")],
        "Other": [("tx_index", 1, "string")],
        "NodeInfo": [("network", 4, "string"), ("other", 8, "Other")],
        "NodeResponse": [("default_node_info", 1, "NodeInfo")],
        "SyncResponse": [("syncing", 1, "bool")],
        "Header": [("chain_id", 2, "string"), ("height", 3, "int64")],
        "Block": [("header", 1, "Header")],
        "BlockId": [("hash", 1, "bytes")],
        "BlockResponse": [
            ("block_id", 1, "BlockId"),
            ("block", 2, "Block"),
            ("sdk_block", 3, "Block"),
        ],
    }
    scalars = {"string": 9, "int64": 3, "bool": 8, "bytes": 12}
    for name, fields in definitions.items():
        msg = file.message_type.add(name=name)
        for field_name, number, kind in fields:
            field = msg.field.add(name=field_name, number=number, label=1)
            field.type = scalars.get(kind, 11)
            if kind not in scalars:
                field.type_name = ".checker." + kind
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return {
        name: message_factory.GetMessageClass(pool.FindMessageTypeByName("checker." + name))
        for name in definitions
    }


MESSAGES = message_types()
PREFIX = "cosmos.base.tendermint.v1beta1.Service/"
METHODS = {
    "GetNodeInfo": ("Empty", "NodeResponse"),
    "GetSyncing": ("Empty", "SyncResponse"),
    "GetLatestBlock": ("Empty", "BlockResponse"),
    "GetBlockByHeight": ("HeightRequest", "BlockResponse"),
}


def codec(method, payload):
    if not method.startswith(PREFIX) or method[len(PREFIX) :] not in METHODS:
        raise ValueError("unsupported Cosmos gRPC method")
    request, response = METHODS[method[len(PREFIX) :]]
    args = {"height": int(payload["height"])} if request == "HeightRequest" else {}
    data = MESSAGES[request](**args).SerializeToString()

    def decode(raw):
        message = MESSAGES[response].FromString(raw)
        if response == "SyncResponse":
            # Absent proto3 bool is false, including a valid empty response.
            return {"syncing": message.syncing}
        return MessageToDict(message)

    return data, decode
